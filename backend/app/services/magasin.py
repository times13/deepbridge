#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
magasin.py — DeepBridge : index des mesures et table des corrections.

PARTAGE DES ROLES
-----------------
    CSV      sortie brute du pipeline, trace de provenance, verifiable a l'oeil.
             La cohorte d'etude EST un CSV : c'est l'artefact que le jury ouvre.
    SQLite   index reconstruit a partir des CSV, plus ce que le pipeline ne
             produit pas : les corrections du radiologue.

Le sens de la dependance compte. L'index se regenere depuis les CSV a tout
moment ; l'inverse serait impossible. En cas de doute sur l'index, on le jette.

POURQUOI UNE BASE MALGRE TOUT
-----------------------------
Ce n'est pas le volume qui l'impose — 148 patients tiennent en memoire. Ce sont
trois besoins que le fichier ne couvre pas :

  * interroger en travers ("tous les axes au-dessus de 70 %") sans ouvrir N
    fichiers ;
  * stocker les corrections, qui referencent un axe, portent un auteur et une
    date, et doivent coexister avec la valeur automatique sans l'ecraser ;
  * supporter deux utilisateurs sans que le dernier ecrivain gagne.

LA TABLE DES CORRECTIONS
------------------------
Elle enregistre CE QUE LE RADIOLOGUE A DIT **et** CE QUE LA MACHINE DISAIT AU
MEME MOMENT. Ne garder que la valeur humaine perdrait la comparaison des que le
pipeline evolue : on ne saurait plus contre quelle version la correction a ete
faite. C'est ce couple qui constitue la verite terrain, et il ne se reconstitue
pas apres coup.
"""

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;

-- Index des axes. Reconstruit depuis les CSV : aucune donnee n'y est unique.
CREATE TABLE IF NOT EXISTS axes (
    patient      TEXT NOT NULL,
    cote         TEXT NOT NULL,
    cohorte      TEXT NOT NULL,          -- 'etude' | 'clinique'
    verdict      TEXT,
    nascet_pct   REAL,
    d_min_mm     REAL,
    d_ref_mm     REAL,
    z_minimum    INTEGER,
    cause        TEXT,
    source       TEXT NOT NULL,          -- chemin du CSV d'origine
    indexe_le    TEXT NOT NULL,
    donnees      TEXT,                   -- la ligne complete, en JSON
    PRIMARY KEY (patient, cote, cohorte)
);
CREATE INDEX IF NOT EXISTS idx_axes_verdict ON axes(cohorte, verdict);
CREATE INDEX IF NOT EXISTS idx_axes_nascet  ON axes(cohorte, nascet_pct);

-- Corrections du radiologue. Jamais ecrasees : chaque relecture ajoute une
-- ligne, l'historique est conserve.
CREATE TABLE IF NOT EXISTS corrections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient       TEXT NOT NULL,
    cote          TEXT NOT NULL,
    cohorte       TEXT NOT NULL,
    auteur        TEXT,
    saisi_le      TEXT NOT NULL,
    -- ce que dit l'humain
    verdict_humain   TEXT NOT NULL,      -- mesurable | non_mesurable | pas_de_stenose
    nascet_humain    REAL,
    d_min_humain     REAL,
    d_ref_humain     REAL,
    z_humain         INTEGER,
    commentaire      TEXT,
    -- ce que disait la machine AU MOMENT de la correction
    verdict_auto     TEXT,
    nascet_auto      REAL,
    -- pourquoi ce couple : sans lui, on ne saurait plus contre quelle version
    -- du pipeline la correction a ete faite.
    accord           INTEGER             -- 1 si les deux verdicts concordent
);
CREATE INDEX IF NOT EXISTS idx_corr_axe ON corrections(patient, cote, cohorte);
"""

# Colonnes promues en colonnes SQL parce qu'on les interroge. Le reste de la
# ligne reste en JSON : recopier 29 colonnes dans un schema fige obligerait a
# une migration a chaque evolution du pipeline.
PROMUES = {
    "verdict": ("verdict", str),
    "nascet_pct": ("nascet_pct", float),
    "d_min_mm": ("d_min_mm", float),
    "d_ref_mm": ("d_ref_mm", float),
    "z_minimum": ("z_minimum", int),
    "cause_dominante": ("cause", str),
}


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conv(v, t):
    if v is None or v == "":
        return None
    try:
        return t(float(v)) if t is int else t(v)
    except (TypeError, ValueError):
        return None


class Magasin:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.base.parent.mkdir(parents=True, exist_ok=True)
        with self._cx() as cx:
            cx.executescript(SCHEMA)

    def _cx(self):
        cx = sqlite3.connect(self.base, timeout=30)
        cx.row_factory = sqlite3.Row
        return cx

    # -- indexation --------------------------------------------------------- #

    def indexer_csv(self, f: Path, cohorte: str) -> int:
        """Charge un CSV dans l'index. Idempotent : reindexer ne duplique pas."""
        import json
        if not f.exists():
            return 0
        with open(f, encoding="utf-8-sig", newline="") as fh:
            lignes = list(csv.DictReader(fh, delimiter=";"))
        n, ts = 0, maintenant()
        with self._cx() as cx:
            for l in lignes:
                pat, cote = l.get("patient"), l.get("cote")
                if not pat or not cote:
                    continue
                vals = {sql: _conv(l.get(src), t)
                        for src, (sql, t) in PROMUES.items()}
                cx.execute(
                    "INSERT INTO axes (patient,cote,cohorte,verdict,nascet_pct,"
                    "d_min_mm,d_ref_mm,z_minimum,cause,source,indexe_le,donnees) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(patient,cote,cohorte) DO UPDATE SET "
                    "verdict=excluded.verdict, nascet_pct=excluded.nascet_pct, "
                    "d_min_mm=excluded.d_min_mm, d_ref_mm=excluded.d_ref_mm, "
                    "z_minimum=excluded.z_minimum, cause=excluded.cause, "
                    "source=excluded.source, indexe_le=excluded.indexe_le, "
                    "donnees=excluded.donnees",
                    (pat, cote, cohorte, vals["verdict"], vals["nascet_pct"],
                     vals["d_min_mm"], vals["d_ref_mm"], vals["z_minimum"],
                     vals["cause"], str(f), ts,
                     json.dumps(l, ensure_ascii=False)))
                n += 1
        return n

    def reindexer(self, reference: Path, racine_dossiers: Path) -> dict:
        """Reconstruit l'index a partir des CSV. Sans effacer les corrections :
        elles ne sont pas derivables et seraient irrecuperables."""
        with self._cx() as cx:
            cx.execute("DELETE FROM axes")
        bilan = {"etude": self.indexer_csv(reference, "etude"), "clinique": 0}
        if racine_dossiers and racine_dossiers.is_dir():
            for f in sorted(racine_dossiers.glob("*/nascet.csv")):
                bilan["clinique"] += self.indexer_csv(f, "clinique")
        return bilan

    # -- interrogation ------------------------------------------------------ #

    def axes(self, cohorte: str = "etude", verdict: str = None,
             nascet_min: float = None) -> list[dict]:
        sql = "SELECT * FROM axes WHERE cohorte=?"
        args = [cohorte]
        if verdict:
            sql += " AND verdict=?"
            args.append(verdict)
        if nascet_min is not None:
            sql += " AND nascet_pct >= ?"
            args.append(nascet_min)
        sql += " ORDER BY patient, cote"
        with self._cx() as cx:
            return [dict(r) for r in cx.execute(sql, args)]

    def compter(self, cohorte: str = "etude") -> dict:
        with self._cx() as cx:
            return {r["verdict"]: r["n"] for r in cx.execute(
                "SELECT verdict, COUNT(*) n FROM axes WHERE cohorte=? "
                "GROUP BY verdict", (cohorte,))}

    # -- corrections --------------------------------------------------------- #

    def corriger(self, patient: str, cote: str, cohorte: str,
                 verdict_humain: str, auteur: str = None,
                 nascet_humain: float = None, d_min: float = None,
                 d_ref: float = None, z: int = None,
                 commentaire: str = None) -> dict:
        with self._cx() as cx:
            r = cx.execute(
                "SELECT verdict, nascet_pct FROM axes "
                "WHERE patient=? AND cote=? AND cohorte=?",
                (patient, cote, cohorte)).fetchone()
            v_auto = r["verdict"] if r else None
            n_auto = r["nascet_pct"] if r else None

            # Concordance entre le verdict humain et le verdict machine.
            # C'est cette colonne qui valide le classifieur : sans elle, on
            # aurait des mesures corrigees mais aucune mesure de l'accord.
            publie = v_auto in ("mesure", "mesure_incertaine")
            accord = int(
                (verdict_humain == "mesurable" and publie)
                or (verdict_humain == "non_mesurable" and v_auto == "non_calculable")
                or (verdict_humain == "pas_de_stenose" and v_auto == "pas_de_stenose")
            )
            cur = cx.execute(
                "INSERT INTO corrections (patient,cote,cohorte,auteur,saisi_le,"
                "verdict_humain,nascet_humain,d_min_humain,d_ref_humain,"
                "z_humain,commentaire,verdict_auto,nascet_auto,accord) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (patient, cote, cohorte, auteur, maintenant(), verdict_humain,
                 nascet_humain, d_min, d_ref, z, commentaire,
                 v_auto, n_auto, accord))
            cid = cur.lastrowid
        return self.correction(cid)

    def correction(self, cid: int) -> dict | None:
        with self._cx() as cx:
            r = cx.execute("SELECT * FROM corrections WHERE id=?",
                           (cid,)).fetchone()
        return dict(r) if r else None

    def corrections(self, patient: str = None, cote: str = None) -> list[dict]:
        sql, args = "SELECT * FROM corrections", []
        if patient:
            sql += " WHERE patient=?"
            args.append(patient)
            if cote:
                sql += " AND cote=?"
                args.append(cote)
        sql += " ORDER BY saisi_le DESC"
        with self._cx() as cx:
            return [dict(r) for r in cx.execute(sql, args)]

    def derniere_correction(self, patient: str, cote: str) -> dict | None:
        with self._cx() as cx:
            r = cx.execute(
                "SELECT * FROM corrections WHERE patient=? AND cote=? "
                "ORDER BY saisi_le DESC, id DESC LIMIT 1",
                (patient, cote)).fetchone()
        return dict(r) if r else None

    def accord(self) -> dict:
        """Taux d'accord entre verdict automatique et jugement humain.

        C'est la validation du classifieur de verdicts, et un resultat a part
        entiere : sur une chaine qui s'abstient 4 fois sur 10, savoir si elle
        s'abstient A RAISON vaut autant que la mesure elle-meme.

        Seule la DERNIERE correction de chaque axe compte : une relecture
        revisee ne doit pas peser deux fois.
        """
        with self._cx() as cx:
            lignes = [dict(r) for r in cx.execute(
                "SELECT c.* FROM corrections c JOIN (SELECT patient, cote, "
                "MAX(id) mid FROM corrections GROUP BY patient, cote) d "
                "ON c.id = d.mid")]
        if not lignes:
            return {"n": 0, "accord": None, "par_verdict": {}}
        par = {}
        for l in lignes:
            k = l["verdict_auto"] or "inconnu"
            s = par.setdefault(k, {"n": 0, "accord": 0})
            s["n"] += 1
            s["accord"] += l["accord"]
        for s in par.values():
            s["taux"] = round(100 * s["accord"] / s["n"], 1)
        return {
            "n": len(lignes),
            "accord": round(100 * sum(l["accord"] for l in lignes) / len(lignes), 1),
            "par_verdict": par,
        }

    def exporter_verite_terrain(self, f: Path) -> int:
        """Exporte le couple (jugement humain, verdict machine) en CSV.

        Ce fichier est le jeu de validation : il permet de comparer une future
        version du pipeline a la meme reference humaine.
        """
        lignes = self.corrections()
        if not lignes:
            return 0
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(lignes[0].keys()),
                               delimiter=";")
            w.writeheader()
            w.writerows(lignes)
        return len(lignes)
