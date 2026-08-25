"""
Lecture des mesures produites par le pipeline.

DEUX MAGASINS, JAMAIS CONFONDUS
-------------------------------
    reference   cohorte d'étude, figée à 292 axes, LECTURE SEULE.
                Les chiffres du mémoire ne sont vérifiables que si ce
                fichier ne bouge plus.
    dossiers    un sous-dossier par patient analysé par l'application.
                Issue à J30 inconnue : ces patients ne peuvent entrer ni
                dans les statistiques de cohorte, ni dans la base de
                comparaison du risque.

CE QUI TRAVERSE LA COUCHE
-------------------------
Pas un pourcentage : le quadruplet (verdict, valeur, justification, pièce à
conviction). Trois règles tenues partout :

  * `verdict` n'est jamais absent — une valeur sans statut se lit comme une
    mesure ferme ;
  * toute valeur porte `borne = "basse"` — la détection de bord à mi-hauteur
    place le contour environ 0,19 mm trop loin du centre, ce qui surestime
    le lumen résiduel et donc SOUS-ESTIME la sténose ;
  * les axes refusés ne sont jamais masqués.
"""
import json
import math
from pathlib import Path

import pandas as pd
from fastapi import HTTPException

LIBELLE_VERDICT = {
    "mesure": "Mesure",
    "mesure_incertaine": "Mesure incertaine",
    "pas_de_stenose": "Pas de sténose focale",
    "non_calculable": "Non mesurable",
    "region_incompatible": "Région incompatible",
}

CONDUITE = {
    "mesure": "Ratio exploitable. Vérifier la section au minimum.",
    "mesure_incertaine": "Le voisinage du minimum est dégradé. Relecture visuelle recommandée.",
    "pas_de_stenose": "Le vaisseau s'affine régulièrement, sans rétrécissement localisé. Aucun ratio n'a de sens ici.",
    "non_calculable": "Mesure manuelle nécessaire. La coupe est indiquée ci-dessous.",
    "region_incompatible": "Cet examen ne couvre pas la région cervicale.",
}


def formuler_cause(cause: str) -> str:
    """Traduit le motif interne du pipeline en langage clinique.

    Le radiologue doit lire ce qui s'est passé dans l'image, pas quel test
    du code a échoué.
    """
    c = (cause or "").lower()
    if "rehaussement" in c:
        return ("Rehaussement insuffisant : pas de plateau luminal exploitable. "
                "Acquisition trop tardive, ou axe sorti du vaisseau.")
    if c.startswith("os "):
        return ("Structure osseuse dans la portée des rayons. Le bord n'est pas "
                "localisable dans cette direction.")
    if "incoherent" in c or "incohérent" in c:
        return "Contour détecté incohérent avec le masque de segmentation."
    if "aberrant" in c:
        return "Contour aberrant : section trop allongée pour être un lumen."
    if "circonference" in c or "circonférence" in c:
        return "Moins de 60 % de la circonférence lisible."
    return cause or "Motif non renseigné"


def _f(v):
    """float ou None — NaN ne survit pas à la sérialisation JSON."""
    try:
        x = float(v)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


class Mesures:
    def __init__(self, reference: Path, dossiers: Path, mesures: Path):
        self.reference = Path(reference)
        self.dossiers = Path(dossiers)
        self.mesures = Path(mesures)
        self.recharger()

    # -- chargement --------------------------------------------------------- #

    def _lire(self, f: Path, cohorte: str) -> pd.DataFrame:
        d = pd.read_csv(f, sep=";", encoding="utf-8-sig", dtype={"patient": str})
        d["cohorte"] = cohorte
        return d

    def recharger(self):
        """Relit les deux magasins. Appelé après chaque analyse : un patient
        qui vient d'être traité doit apparaître sans redémarrer le service.

        La référence est relue elle aussi, mais jamais écrite.
        """
        morceaux = []
        if self.reference.exists():
            morceaux.append(self._lire(self.reference, "etude"))
        if self.dossiers.is_dir():
            for f in sorted(self.dossiers.glob("*/nascet.csv")):
                try:
                    morceaux.append(self._lire(f, "clinique"))
                except Exception:
                    continue    # un dossier illisible ne doit pas tuer le service
        if not morceaux:
            self.df = pd.DataFrame(columns=["patient", "cote", "verdict",
                                            "cohorte"])
            return
        d = pd.concat(morceaux, ignore_index=True)

        # Ratio implicite : d_min et d_ref existent aussi sur les axes refusés.
        # C'est la FIABILITÉ de leur mesure qui a été jugée insuffisante, pas
        # leur existence. Jamais publié comme une mesure — sert uniquement à
        # trier la pile des refus par sévérité présumée.
        d["nascet_implicite"] = 100.0 * (1.0 - d["d_min_mm"] / d["d_ref_mm"])

        # La valeur brute et la valeur débiaisée tombent de part et d'autre de
        # 70 % : deux conduites opposées pour un même axe.
        d["alerte_seuil"] = (d["nascet_pct"] < 70) & \
                            (d["expl_nascet_corrige_biais"] >= 70)
        self.df = d

    def existe(self, patient: str, cote: str) -> bool:
        return bool(((self.df.patient == patient) & (self.df.cote == cote)).any())

    # -- sérialisation ------------------------------------------------------ #

    def _artefacts(self, patient: str, cote: str) -> dict:
        sorties = {}
        for racine in (self.mesures, self.dossiers / patient):
            base = racine / f"{patient}_{cote}"
            if base.is_dir():
                for f in sorted(base.glob("*.png")):
                    sorties[f.stem] = f"/api/artefacts/{patient}/{cote}/{f.name}"
        return sorties

    def axe(self, patient: str, cote: str, complet: bool = False) -> dict:
        sel = self.df[(self.df.patient == patient) & (self.df.cote == cote)]
        if sel.empty:
            raise HTTPException(404, f"axe {patient}/{cote} inconnu")
        # Patient d'étude réanalysé par l'application : on montre la version
        # clinique, plus récente, sans jamais toucher à la référence.
        if len(sel) > 1:
            clin = sel[sel.cohorte == "clinique"]
            sel = clin if len(clin) else sel
        r = sel.iloc[0]

        verdict = str(r["verdict"])
        publie = verdict in ("mesure", "mesure_incertaine")
        out = {
            "patient": patient,
            "cote": cote,
            "cohorte": str(r.get("cohorte", "etude")),
            "verdict": verdict,
            "verdict_libelle": LIBELLE_VERDICT.get(verdict, verdict),
            "conduite": CONDUITE.get(verdict, ""),
            # 'nascet_pct' n'existe QUE si le verdict autorise une publication.
            "nascet_pct": _f(r["nascet_pct"]) if publie else None,
            "borne": "basse" if publie else None,
            "nascet_corrige": _f(r["expl_nascet_corrige_biais"]) if publie else None,
            "alerte_seuil": bool(r["alerte_seuil"]) if publie else False,
            "d_min_mm": _f(r["d_min_mm"]),
            "d_ref_mm": _f(r["d_ref_mm"]),
            "z_minimum": _i(r["z_minimum"]),
            "nascet_implicite": _f(r["nascet_implicite"]),
        }
        if verdict == "non_calculable":
            out["cause"] = formuler_cause(str(r.get("cause_dominante", "")))
            out["cause_brute"] = str(r.get("cause_dominante", ""))

        if complet:
            out["preuve"] = {
                "sections_totales": _i(r.get("n_sections")),
                "sections_retenues": _i(r.get("n_retenues")),
                "pct_retenues": _f(r.get("pct_retenues")),
                "frac_vaisseau_pct": _f(r.get("frac_vaisseau_pct")),
                "frac_voisinage_pct": _f(r.get("frac_voisinage_pct")),
                "hu_lumen_median": _f(r.get("hu_lumen_median")),
                "obliquite_mediane": _f(r.get("obliquite_mediane")),
                "espacement_mm": _f(r.get("espacement_mm")),
                "stenose_aire_pct": _f(r.get("stenose_aire_pct")),
            }
            out["artefacts"] = self._artefacts(patient, cote)
        return out

    # -- vues ---------------------------------------------------------------- #

    def synthese(self, cohorte: str = "etude") -> dict:
        # Par défaut la cohorte d'ÉTUDE seule : les chiffres affichés en tête
        # d'écran sont ceux du mémoire et ne doivent pas dériver à mesure que
        # des patients cliniques arrivent.
        d = self.df[self.df.cohorte == cohorte]
        if d.empty:
            return {"cohorte": cohorte, "axes": 0, "patients": 0,
                    "verdicts": [], "mediane_publiee": None,
                    "n_alertes_seuil": 0, "n_refus": 0}
        counts = d["verdict"].value_counts().to_dict()
        pub = d[d.verdict.isin(["mesure", "mesure_incertaine"])]
        return {
            "cohorte": cohorte,
            "axes": len(d),
            "patients": int(d.patient.nunique()),
            "verdicts": [
                {"code": k, "libelle": LIBELLE_VERDICT.get(k, k),
                 "n": int(counts.get(k, 0)),
                 "pct": round(100 * counts.get(k, 0) / len(d), 1)}
                for k in ("mesure", "mesure_incertaine", "pas_de_stenose",
                          "non_calculable")
            ],
            "mediane_publiee": _f(pub.nascet_pct.median()),
            "n_alertes_seuil": int(pub["alerte_seuil"].sum()),
            "n_refus": int((d.verdict == "non_calculable").sum()),
        }

    def liste(self, verdict: str = None, cohorte: str = "etude") -> list:
        d = self.df[self.df.cohorte == cohorte]
        if verdict:
            d = d[d.verdict == verdict]
        d = d.sort_values(["patient", "cote"])
        return [self.axe(r.patient, r.cote) for r in d.itertuples()]

    def file_prioritaire(self) -> list:
        """Les refus, triés par sévérité présumée décroissante.

        La chaîne ne sait pas mesurer les cas graves, mais elle sait les
        reconnaître : les refus sont significativement plus sténosés que les
        mesures publiées (56,8 % contre 46,8 %, p = 3e-7), et 16,8 %
        dépasseraient 70 % contre 5,2 %.

        C'est donc une file de travail, pas un journal d'échecs.
        """
        d = self.df[(self.df.verdict == "non_calculable")
                    & (self.df.cohorte == "etude")]
        d = d.sort_values("nascet_implicite", ascending=False)
        return [self.axe(r.patient, r.cote) for r in d.itertuples()]

    def patient(self, patient: str, seuil_symp: float,
                seuil_asymp: float) -> dict:
        sel = self.df[self.df.patient == patient]
        if sel.empty:
            raise HTTPException(404, f"patient {patient} inconnu")
        axes = [self.axe(patient, c, complet=True) for c in sel.cote.unique()]
        pub = [a for a in axes if a["nascet_pct"] is not None]
        reco = None
        if pub:
            pire = max(pub, key=lambda a: a["nascet_pct"])
            # Le statut symptomatique n'est pas dans nascet.csv : sans lui on
            # ne peut pas trancher entre les deux seuils. On expose donc les
            # deux, et l'écran demande l'information au clinicien.
            reco = {
                "cote_le_plus_atteint": pire["cote"],
                "nascet_pct": pire["nascet_pct"],
                "au_dessus_seuil_symptomatique": pire["nascet_pct"] >= seuil_symp,
                "au_dessus_seuil_asymptomatique": pire["nascet_pct"] >= seuil_asymp,
                "seuil_symptomatique": seuil_symp,
                "seuil_asymptomatique": seuil_asymp,
            }
        return {"patient": patient, "axes": axes, "recommandation": reco}
