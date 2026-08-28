#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
travaux.py — DeepBridge : file de travaux pour l'analyse d'un dossier DICOM.

POURQUOI UNE FILE
-----------------
La segmentation dure 12,5 minutes en mediane par patient, et jusqu'a pres de
trois heures sur les volumes les plus lourds. Aucune requete HTTP ne tient
cette duree. Le depot d'un dossier cree donc un TRAVAIL, et l'interface
interroge son etat.

POURQUOI PAS CELERY
-------------------
Celery et Redis supposent deux services supplementaires, penibles a installer
sur Windows et a deboguer pour une equipe qui n'en a pas besoin. Ici, un poste
unique traite un examen a la fois. Une table SQLite et un thread de travail
suffisent : rien a installer, l'etat survit a un redemarrage, et le contrat
d'API est le meme. Le remplacement par Celery, si la charge le justifie un
jour, ne touchera pas les endpoints.

ETATS
-----
    en_attente -> conversion -> segmentation -> axe -> mesure -> termine
                                                              -> echec
                                                              -> annule

Chaque etape est SAUTEE si son resultat existe deja sur le disque. Relancer un
travail interrompu reprend la ou il s'est arrete : sur une chaine de plusieurs
heures, refaire le travail accompli n'est pas acceptable.

IMPORTANT — la completude ne se juge pas sur l'existence d'un dossier. Un
processus interrompu laisse un dossier 'seg/' partiel qui serait compte comme
un succes. On verifie la presence effective des fichiers de labels attendus.
"""

import os
import json
import shutil
import sqlite3
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue, Empty

from app.validation import prevol, controle_volume

# --------------------------------------------------------------------------- #

ETAPES = ["prevol", "conversion", "segmentation", "axe", "mesure"]

# Labels dont la presence atteste qu'une segmentation est complete.
# Les jugulaires ne servent pas a la mesure mais au controle de fuite veineuse :
# elles doivent donc etre produites systematiquement.
LABELS_INTERNE = [
    "internal_carotid_artery_left.nii.gz",
    "internal_carotid_artery_right.nii.gz",
    "internal_jugular_vein_left.nii.gz",
    "internal_jugular_vein_right.nii.gz",
]
LABELS_COMMUNE = [
    "common_carotid_artery_left.nii.gz",
    "common_carotid_artery_right.nii.gz",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS travaux (
    id            TEXT PRIMARY KEY,
    patient_id    TEXT,
    dossier_depot TEXT NOT NULL,
    etat          TEXT NOT NULL,
    etape         TEXT,
    progression   INTEGER DEFAULT 0,
    message       TEXT,
    erreur        TEXT,
    cree_le       TEXT NOT NULL,
    demarre_le    TEXT,
    fini_le       TEXT,
    duree_s       REAL,
    journal       TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_etat ON travaux(etat);
"""

def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Travail:
    id: str
    patient_id: str | None
    dossier_depot: str
    etat: str
    etape: str | None
    progression: int
    message: str | None
    erreur: str | None
    cree_le: str
    demarre_le: str | None
    fini_le: str | None
    duree_s: float | None
    journal: list

    def dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #

class FileTravaux:
    """Stockage SQLite + un thread de travail."""

    def __init__(self, base: Path, racine_resultats: Path, racine_dossiers: Path,
                 pipeline: Path, python: str = None, device: str = "cpu",
                 totalsegmentator: str = "TotalSegmentator"):
        self.base = Path(base)
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self.racine_resultats = Path(racine_resultats)
        # Racine des dossiers CLINIQUES. Chaque patient analyse par
        # l'application y recoit son propre sous-dossier et son propre CSV.
            #
        # La cohorte d'etude (292 axes) n'est JAMAIS ecrite ici ni ailleurs :
        # elle est figee, et c'est ce qui rend les chiffres du memoire
        # verifiables. Melanger les deux rendrait la mediane publiee, les
        # effectifs par verdict et le test de biais irreproductibles des le
        # premier patient clinique.
        self.racine_dossiers = Path(racine_dossiers)
        self.pipeline = Path(pipeline)
        self.python = python or "python"
        self.device = device
        # L'executable vit dans le venv du pipeline, absent du PATH du
        # processus uvicorn : l'appeler par son nom seul echoue en WinError 2.
        self.totalsegmentator = totalsegmentator

        self._verrou = threading.Lock()
        self._queue: Queue[str] = Queue()
        self._annules: set[str] = set()
        self._arret = threading.Event()

        with self._cx() as cx:
            cx.executescript(SCHEMA)

        # Un travail laisse "en cours" par un arret brutal doit repartir en
        # attente, sinon il reste bloque pour toujours.
        self._reprendre_orphelins()

        self._worker = threading.Thread(target=self._boucle, daemon=True,
                                        name="deepbridge-worker")
        self._worker.start()

        # -- stockage ---------------------------------------------------------- #

    def _cx(self):
        cx = sqlite3.connect(self.base, timeout=30)
        cx.row_factory = sqlite3.Row
        return cx

    def _lire(self, tid: str) -> Travail | None:
        with self._cx() as cx:
            r = cx.execute("SELECT * FROM travaux WHERE id=?", (tid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["journal"] = json.loads(d["journal"] or "[]")
        return Travail(**d)

    def _maj(self, tid: str, **champs):
        if not champs:
            return
        if "journal" in champs:
            champs["journal"] = json.dumps(champs["journal"], ensure_ascii=False)
        sql = ", ".join(f"{k}=?" for k in champs)
        with self._verrou, self._cx() as cx:
            cx.execute(f"UPDATE travaux SET {sql} WHERE id=?",
                    (*champs.values(), tid))

    def _noter(self, tid: str, texte: str):
        t = self._lire(tid)
        if not t:
            return
        j = t.journal + [{"t": maintenant(), "m": texte}]
        self._maj(tid, journal=j[-60:])   # borne : un journal n'est pas un log

    def _reprendre_orphelins(self):
        with self._cx() as cx:
            lignes = cx.execute(
                "SELECT id FROM travaux WHERE etat NOT IN "
                "('termine','echec','annule','en_attente')").fetchall()
        for r in lignes:
            self._maj(r["id"], etat="en_attente", etape=None,
                    message="repris apres redemarrage du service")
            self._queue.put(r["id"])

    # -- API publique ------------------------------------------------------ #

    def deposer(self, dossier_depot: Path, patient_id: str | None = None) -> Travail:
        tid = uuid.uuid4().hex[:12]
        with self._verrou, self._cx() as cx:
            cx.execute(
                "INSERT INTO travaux (id, patient_id, dossier_depot, etat, "
                "progression, message, cree_le) VALUES (?,?,?,?,?,?,?)",
                (tid, patient_id, str(dossier_depot), "en_attente", 0,
                "en file", maintenant()))
        self._queue.put(tid)
        return self._lire(tid)

    def etat(self, tid: str) -> Travail | None:
        return self._lire(tid)

    def liste(self, limite: int = 50) -> list[Travail]:
        with self._cx() as cx:
            lignes = cx.execute(
                "SELECT id FROM travaux ORDER BY cree_le DESC LIMIT ?",
                (limite,)).fetchall()
        return [self._lire(r["id"]) for r in lignes]

    def annuler(self, tid: str) -> bool:
        t = self._lire(tid)
        if not t or t.etat in ("termine", "echec", "annule"):
            return False
        self._annules.add(tid)
        if t.etat == "en_attente":
            self._maj(tid, etat="annule", fini_le=maintenant(),
                    message="annule avant demarrage")
        else:
            self._maj(tid, message="annulation demandee, fin de l'etape en cours")
        return True

    def arreter(self):
        self._arret.set()

    # -- worker ------------------------------------------------------------ #

    def _boucle(self):
        while not self._arret.is_set():
            try:
                tid = self._queue.get(timeout=1.0)
            except Empty:
                continue
            if tid in self._annules:
                self._annules.discard(tid)
                continue
            try:
                self._executer(tid)
            except Exception:
                self._maj(tid, etat="echec", fini_le=maintenant(),
                          erreur=traceback.format_exc()[-2000:],
                message="erreur interne du service")

    def _annule(self, tid: str) -> bool:
        if tid in self._annules:
            self._annules.discard(tid)
            self._maj(tid, etat="annule", fini_le=maintenant(),
                    message="annule")
            return True
        return False

    def _executer(self, tid: str):
        t = self._lire(tid)
        depot = Path(t.dossier_depot)
        t0 = time.time()

        # --- 0. pre-vol ---------------------------------------------------- #
        # Deux secondes de lecture d'en-tetes contre douze minutes de
        # segmentation. Et surtout : un message JUSTE. Sans ce controle, un
        # examen hors-sujet traverse toute la chaine et ressort en
        # « rehaussement insuffisant » — une cause qui n'est pas la vraie.
        self._maj(tid, etat="prevol", etape="prevol", progression=1,
                demarre_le=maintenant(), message="controle de recevabilite")
        fichiers = self._fichiers_dicom(depot)
        r = prevol(fichiers)
        self._noter(tid, f"pre-vol : {r.issue} — {r.message[:90]}")
        for x in r.reserves:
            self._noter(tid, f"reserve : {x[:90]}")
        if not r.ok:
            self._maj(tid, etat="echec", etape="prevol", fini_le=maintenant(),
                    message=r.message,
                    erreur="\n".join(r.bloquants)[:2000])
            return
        if r.indices.get("patient_id"):
            self._maj(tid, patient_id=r.indices["patient_id"])

        self._maj(tid, etat="conversion", etape="conversion", progression=3,
                message="lecture du dossier DICOM")

        # --- 1. conversion : PatientID puis ct.nii.gz --------------------- #
        pid = t.patient_id or r.indices.get("patient_id") or self._patient_id(depot)
        if not pid:
            self._maj(tid, etat="echec", fini_le=maintenant(),
                    message="aucun PatientID lisible dans ce dossier",
                    erreur="Le dossier ne contient pas de serie DICOM "
                            "exploitable, ou le tag PatientID (0010,0020) "
                            "est absent.")
            return
        self._maj(tid, patient_id=pid)
        cible = self.racine_resultats / pid
        ct = cible / "ct.nii.gz"

        if ct.exists():
            self._noter(tid, "ct.nii.gz deja present, conversion sautee")
            self._maj(tid, progression=20)
        else:
            self._noter(tid, "conversion DICOM vers NIfTI")
            ok, msg = self._lancer([
                self.python, str(self.pipeline / "etape0_lot_segmentation.py"),
                "--scans", str(self._racine_scan(depot, tid)), "--out", str(self.racine_resultats),
                "--seulement-ct", "--silencieux",
                ], tid, timeout=1800)
            if not ok:
                return self._echec(tid, "conversion", msg)
            self._maj(tid, progression=20)
        if self._annule(tid):
            return

        # --- 2. segmentation --------------------------------------------- #
        self._maj(tid, etat="segmentation", etape="segmentation", progression=22,
                message="segmentation en cours — comptez une quinzaine de minutes")
        if self._segmentation_complete(cible):
            self._noter(tid, "segmentation deja complete, etape sautee")
        else:
            self._noter(tid, "TotalSegmentator : carotides internes et jugulaires")
            ok, msg = self._lancer([
                self.totalsegmentator, "-i", str(ct), "-o", str(cible / "seg"),
                "-ta", "headneck_bones_vessels", "--device", self.device,
                ], tid, timeout=14400)
            if not ok:
                return self._echec(tid, "segmentation", msg)
            self._maj(tid, progression=55,
                      message="segmentation de la carotide commune")
            self._noter(tid, "TotalSegmentator : carotides communes")
            # Sans la commune, la mesure porte AU-DESSUS du bulbe, donc
            # au-dessus du site ou siege la plupart des lesions.
            ok, msg = self._lancer([
                self.totalsegmentator, "-i", str(ct), "-o", str(cible / "seg_total"),
                "-ta", "total", "--device", self.device, "--roi_subset",
                "common_carotid_artery_left", "common_carotid_artery_right",
                ], tid, timeout=14400)
            if not ok:
                return self._echec(tid, "segmentation", msg)
        # --- 2bis. confirmation de la region ------------------------------ #
        # Les en-tetes mentent : BodyPartExamined est souvent vide. Ce controle
        # ne depend d'aucun tag et voit ce que le modele a reellement trouve.
        rv = controle_volume(cible / "seg")
        self._noter(tid, f"controle volume : {rv.issue} — {rv.message[:90]}")
        for x in rv.reserves:
            self._noter(tid, f"reserve : {x[:90]}")
        if not rv.ok:
            self._maj(tid, etat="echec", etape="segmentation",
                    fini_le=maintenant(), message=rv.message,
                    erreur="\n".join(rv.bloquants)[:2000])
            return

        self._maj(tid, progression=70)
        if self._annule(tid):
            return

        # --- 3 et 4. axe puis mesure, cote par cote ----------------------- #
        for i, cote in enumerate(("gauche", "droite")):
            self._maj(tid, etat="axe", etape="axe", progression=70 + i * 10,
                    message=f"ligne centrale — carotide {cote}")
            ok, msg = self._lancer([
                self.python,
                str(self.pipeline / "etape2c_centerline_geodesique.py"),
                "--patient", str(cible), "--cote", cote,
                "--out", str(self._dossier(pid)), "--avec-commune",
            ], tid, timeout=1800)
            if not ok:
                self._noter(tid, f"axe {cote} en echec : {msg[:200]}")
                continue

            self._maj(tid, etat="mesure", etape="mesure",
                    progression=80 + i * 8,
                    message=f"mesure FWHM — carotide {cote}")
            ok, msg = self._lancer([
                self.python, str(self.pipeline / "etape2d_fwhm.py"),
                "--patient", str(cible), "--cote", cote,
                "--out", str(self._dossier(pid)), "--marge-mm", "5",
                "--csv", str(self._csv(pid)),
            ], tid, timeout=1800)
            if not ok:
                self._noter(tid, f"mesure {cote} en echec : {msg[:200]}")
            if self._annule(tid):
                return

        # --- bilan --------------------------------------------------------- #
        # etape2d_fwhm AJOUTE une ligne au CSV. Reanalyser un patient deja
        # traite y laisserait donc deux lignes pour le meme axe, et l'ecran de
        # revue en afficherait une au hasard. On ne garde que la derniere.
        self._dedupliquer(self._csv(pid))

        # Un cote en echec n'est pas un echec du travail : le second cote reste
        # exploitable, et l'ecran de revue le montrera.
        resultats = self._resultats(pid)
        if not resultats:
            return self._echec(
                tid, "mesure",
                "Aucune ligne produite dans nascet.csv pour ce patient.")
        self._maj(tid, etat="termine", etape=None, progression=100,
                fini_le=maintenant(), duree_s=round(time.time() - t0, 1),
                message=f"{len(resultats)} axe(s) analyse(s)")
        self._noter(tid, "termine")

    # -- utilitaires -------------------------------------------------------- #

    def _echec(self, tid: str, etape: str, msg: str):
        self._maj(tid, etat="echec", etape=etape, fini_le=maintenant(),
                message=f"echec a l'etape « {etape} »", erreur=msg[:2000])

    def _lancer(self, cmd: list, tid: str, timeout: int) -> tuple[bool, str]:
        self._noter(tid, " ".join(str(c) for c in cmd[:3]) + " …")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout)
        except FileNotFoundError as e:
            return False, f"commande introuvable : {e}"
        except subprocess.TimeoutExpired:
            return False, f"depassement du delai de {timeout} s"
        if r.returncode == 0:
            return True, ""
        # Message entier et non derniere ligne : une exception Python s'imprime
        # sur plusieurs lignes, et un WinError 32 nomme le fichier verrouille.
            return False, ((r.stderr or r.stdout or f"code {r.returncode}")
                       .strip()[-2000:])

    def _fichiers_dicom(self, depot: Path) -> list[Path]:
        """Fichiers d'un depot, tries par nom.

        ranger_depot() prefixe chaque fichier de son rang d'arrivee, donc le
        tri par nom preserve l'ordre du client. Le pre-vol n'a besoin que du
        premier et du dernier ; l'ordre exact des coupes est etabli plus tard
        par le pipeline, sur la position spatiale.
        """
        return sorted(p for p in depot.rglob("*") if p.is_file())

    def _racine_scan(self, depot: Path, tid: str) -> Path:
        """Dossier ne contenant QUE le patient a convertir.

        etape0 parcourt les sous-dossiers de --scans et les traite TOUS.
        Passer depot.parent convenait au televersement, ou le parent ne
        contenait qu'un patient ; sur un depot par chemin, c'est la racine des
        150 dossiers du dataset. D'ou le depassement de delai observe.

        On cree donc un dossier de travail contenant une jonction vers le seul
        patient vise. Aucun octet n'est copie.
        """
        racine = self.base.parent / "scan" / tid
        racine.mkdir(parents=True, exist_ok=True)
        lien = racine / depot.name
        if lien.exists():
            return racine
        try:
            if os.name == "nt":
                # Jonction de repertoire : aucun droit administrateur requis,
                # contrairement au lien symbolique sous Windows.
                subprocess.run(["cmd", "/c", "mklink", "/J",
                                 str(lien), str(depot)],
                capture_output=True, check=True)
            else:
                lien.symlink_to(depot, target_is_directory=True)
        except Exception:
            # Repli : si le dossier depose contient lui-meme des sous-dossiers,
            # etape0 peut le prendre directement pour racine.
            if any(p.is_dir() for p in depot.iterdir()):
                return depot
            raise
        return racine

    def _segmentation_complete(self, cible: Path) -> bool:
        seg, tot = cible / "seg", cible / "seg_total"
        return (all((seg / f).exists() for f in LABELS_INTERNE)
                and all((tot / f).exists() for f in LABELS_COMMUNE))

    def _patient_id(self, depot: Path) -> str | None:
        """PatientID DICOM, sans charger le volume."""
        try:
            import SimpleITK as sitk
        except ImportError:
            return None
        lecteur = sitk.ImageSeriesReader()
        for d in [depot] + [p for p in depot.rglob("*") if p.is_dir()]:
            try:
                uids = lecteur.GetGDCMSeriesIDs(str(d))
            except Exception:
                continue
            for uid in uids:
                fichiers = lecteur.GetGDCMSeriesFileNames(str(d), uid)
                if not fichiers:
                    continue
                r = sitk.ImageFileReader()
                r.SetFileName(fichiers[0])
                try:
                    r.ReadImageInformation()
                    pid = r.GetMetaData("0010|0020").strip()
                except Exception:
                    continue
                if pid:
                    return pid
        return None

    def _dossier(self, pid: str) -> Path:
        """Dossier clinique d'un patient. Un dossier par patient : pas
        d'ecriture concurrente possible, et supprimer un patient revient a
        supprimer un repertoire."""
        d = self.racine_dossiers / pid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _csv(self, pid: str) -> Path:
        return self._dossier(pid) / "nascet.csv"

    def _dedupliquer(self, f: Path):
        """Ne conserve, pour chaque couple (patient, cote), que la derniere ligne.

        L'ordre du fichier est preserve : on garde la position de la PREMIERE
        occurrence et le contenu de la DERNIERE. Un CSV dont les lignes se
        reordonnent a chaque analyse serait illisible en diff.
        """
        import csv
        if not f.exists():
            return
        with open(f, encoding="utf-8-sig", newline="") as fh:
            lecteur = csv.DictReader(fh, delimiter=";")
            colonnes, lignes = lecteur.fieldnames, list(lecteur)
        if not colonnes:
            return
        ordre, garde = [], {}
        for l in lignes:
            cle = (l.get("patient"), l.get("cote"))
            if cle not in garde:
                ordre.append(cle)
            garde[cle] = l
        if len(garde) == len(lignes):
            return
        tmp = f.with_suffix(".csv.tmp")
        with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=colonnes, delimiter=";")
            w.writeheader()
            w.writerows(garde[c] for c in ordre)
        tmp.replace(f)

    def _resultats(self, pid: str) -> list:
        f = self._csv(pid)
        if not f.exists():
            return []
        import csv
        with open(f, encoding="utf-8-sig", newline="") as fh:
            return [l for l in csv.DictReader(fh, delimiter=";")
                    if l.get("patient") == pid]


# --------------------------------------------------------------------------- #

def ranger_depot(fichiers, racine_depots: Path) -> Path:
    """Ecrit les fichiers deposes dans un dossier de travail unique.
    
    Les chemins d'origine sont neutralises : un nom de fichier venant du
    client ne doit jamais pouvoir ecrire hors du dossier de depot.
    """
    dest = racine_depots / uuid.uuid4().hex[:12] / "patient"
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in fichiers:
        nom = Path(f.filename or f"f{n}.dcm").name
        if not nom or nom in (".", ".."):
            continue
        cible = dest / f"{n:05d}_{nom}"
        with open(cible, "wb") as fh:
            shutil.copyfileobj(f.file, fh)
        n += 1
    if n == 0:
        shutil.rmtree(dest.parent, ignore_errors=True)
        raise ValueError("aucun fichier recu")
    return dest
