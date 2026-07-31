# Ingestion des plaquettes commerciales CAGECFI — Design

**Date :** 2026-07-31
**Statut :** validé, prêt pour planification
**Source :** [Drive `CAGECFI_PLAQUETTES COMMERCIALES`](https://drive.google.com/drive/folders/1C_FKZoXHt-ixNKbXnNzYLQQtb6DWJ3t-)

---

## 1. Objectif

Remplacer la base de connaissance actuelle du chatbot CAGECFI (issue du crawl de
`cagecfi.com`) par le contenu des plaquettes commerciales, afin que l'assistant
réponde sur deux périmètres :

1. **L'identité de l'entreprise** — qui est CAGECFI, son positionnement, ses cibles.
2. **Les fonctionnalités de tous les produits** — couverture exhaustive et fidèle.

La cible technique existe déjà : Supabase / pgvector, tables `cagecfi_documents`
et `cagecfi_chunks`, recherche hybride RRF. Ce design ne porte que sur l'**amont**,
c'est-à-dire la production d'un contenu textuel fiable à partir des PDF.

## 2. Audit du corpus (mesuré le 2026-07-31)

L'audit n'est pas une estimation : chaque chiffre ci-dessous provient d'une
extraction réelle sur les fichiers téléchargés.

### 2.1 Volumétrie

| Mesure | Valeur |
| --- | --- |
| Fichiers dans le Drive | 31 PDF + 1 JPG |
| Documents uniques (hash MD5) | 25 |
| Paires de doublons exacts | 6 |
| Documents retenus après exclusion de l'anglais | **22** |

### 2.2 Extractibilité — le constat structurant

Classification par densité de texte extractible (`pypdf`, seuils : `TEXTE` ≥ 400
caractères/page, `MIXTE` ≥ 50, sinon `IMAGE`) :

| Type | Documents uniques |
| --- | --- |
| **IMAGE** (aucun caractère extractible) | **17** |
| TEXTE | 5 |
| MIXTE | 1 |
| Non audités (téléchargements tronqués) | 2 |

**142 pages sur 151, soit 94 %, ne contiennent aucune couche texte.** Ces PDF sont
des visuels exportés depuis un outil de PAO, pas des documents textuels.

Conséquence directe : exécuter `ingest_supabase.py` tel quel sur ce dossier
remplirait la base de documents vides **sans lever d'erreur**. C'est le risque
principal que ce design neutralise.

Les documents concernés incluent précisément les deux cas d'usage visés :

- `CAGECFI_QUI SOMMES NOUS.pdf` → image pure (identité entreprise)
- `PERFECT.pdf` (produit phare), `GOMISE`, `IMMOS`, `SICOM`, `TRADER`, `PAY TAX`,
  `ERP COMPTA`, `GOV MONITOR`, `Plaquette Fiscalisation`, `PROCESSUS CREDIT_JIWAY`
  → images pures (fonctionnalités produits)

Documents disposant d'une couche texte exploitable (traitement sans OCR) :

| Fichier | Pages | Caractères/page |
| --- | --- | --- |
| `MODULES REGLEMENTATAIRES_BIC_LBCFT.pdf` | 2 | 2 579 |
| `SYCEBNL.pdf` | 2 | 1 924 |
| `VISUEL CAGECFI.pdf` | 1 | 1 221 |
| `CLOUD_Administrations.pdf` | 2 | 1 000 |
| `CLOUD_SFD_IMF.pdf` | 2 | 942 |
| `CAGECFI Présentation_Insertion.pdf` | 1 | 82 (mixte) |

### 2.3 Doublons exacts à écarter

Identiques octet pour octet (MD5). À noter : les suffixes `-min` ne désignent
**pas** des versions compressées — ce sont les mêmes fichiers.

1. `CAGECFI_PLAQUETTE PRESENTATION.pdf` == `CAGECFI_QUI SOMMES NOUS.pdf`
2. `CAGECFI_SIG_PERFECT-V-min.pdf` == `PERFECT-VISION-SIG.pdf`
3. `GOV SOLUTIONS_ENG.pdf` == `IT BASED SOLUTIONS GOV_ENG.pdf`
4. `Livret Solutions étatiques-min (2).pdf` == `Livret Solutions étatiques.pdf`
5. `PAY TAX.pdf` == `Plaquette_PAY TAX.pdf`
6. `Solutions de finance digitale-min.pdf` == `Solutions de finance digitale.pdf`

### 2.4 Documents anglais exclus

Décision de cadrage : le prompt système impose des réponses en français, et ces
documents dupliquent sémantiquement des plaquettes françaises déjà présentes. Les
indexer ferait remonter des passages anglais dans le top-k sans apport
d'information.

- `CORE BANKING_PERFECT_ENG.pdf` (4 pages)
- `DIGITAL FINANCE SOLUTIONS_ENG.pdf` (24 pages)
- `GOV SOLUTIONS_ENG.pdf` (24 pages)

Cette exclusion retire 52 pages du volume à traiter par OCR.

### 2.5 Répartition finale du traitement

Les chiffres de la section 2.2 portent sur les 25 documents uniques. Après
exclusion des 3 plaquettes anglaises — toutes de type IMAGE — la répartition des
**22 documents retenus** est la suivante :

| Voie d'extraction | Documents | Détail |
| --- | --- | --- |
| Mistral OCR | **14** | 17 IMAGE − 3 documents anglais |
| Docling sans OCR | **6** | 5 TEXTE + 1 MIXTE |
| À auditer avant routage | **2** | `INTEROPERABILITE.pdf`, `SYCEBNL_CAGECFI.pdf` |

Les deux derniers n'ont pas pu être classés : leurs téléchargements ont été
tronqués pendant l'audit. Ils passeront par `audit_corpus.py` une fois
récupérés intégralement, et suivront le routage correspondant à leur type.

## 3. Choix de la méthode d'extraction

### 3.1 Mesures comparatives Docling avec et sans OCR

Test réalisé sur les deux cas limites du corpus (RapidOCR, `force_full_page_ocr`) :

| Document | Mode | Caractères | Accents corrects | Durée |
| --- | --- | --- | --- | --- |
| `CLOUD_Administrations` (a du texte) | sans OCR | 1 740 | **66** | 14 s |
| `CLOUD_Administrations` | avec OCR | 1 625 | **31** | 212 s |
| `PERFECT` (0 texte) | sans OCR | 205 | 0 | 16 s |
| `PERFECT` | avec OCR | **3 762** | 54 | 266 s |

**L'OCR dégrade les documents qui possèdent déjà une couche texte** (`cceur` au
lieu de `cœur`, `POURQUOIMIGRERVERSLECLOUDAVECCAGECFI` par fusion des espaces) et
**sauve ceux qui n'en ont pas**. Un réglage uniforme est perdant dans les deux sens :
le routage conditionnel est donc une nécessité mesurée, pas une optimisation.

RapidOCR, installé par défaut, s'appuie sur des modèles chinois
(`ch_PP-OCRv4_det/rec`) et n'est pas adapté au français.

### 3.2 Décision : Mistral OCR pour les documents image

`mistral-ocr-latest` est un modèle dédié aux documents (et non un LLM vision
généraliste). D'après la documentation officielle, il :

- gère les **mises en page complexes multi-colonnes** — exactement la structure
  des plaquettes ;
- préserve titres, paragraphes, listes et tableaux, et retourne du **markdown** ;
- expose `table_format`, `extract_header`, `extract_footer`, `include_blocks` ;
- fournit des **scores de confiance**, exploitables pour signaler les pages
  douteuses ;
- accepte un PDF par URL publique, base64, ou upload cloud.

Alternatives écartées : OCR local + correction LLM (qualité brute insuffisante,
correction à l'aveugle sans voir la page) ; curation manuelle (1 à 2 jours, non
rejouable lors des mises à jour de plaquettes).

### 3.3 Validation sur le corpus réel (2026-07-31)

Trois appels réels à l'API, sur les cas représentatifs du corpus :

| Document | Taille | Pages | Durée | Débit | Accents |
| --- | --- | --- | --- | --- | --- |
| `PERFECT.pdf` | 8,1 Mo | 4 | 14,5 s | 3,6 s/p | 73 |
| `CAGECFI_QUI SOMMES NOUS.pdf` | 11,1 Mo | 4 | 20,4 s | 5,1 s/p | 129 |
| `Livret Solutions étatiques.pdf` | 6,4 Mo | 24 | 23,8 s | **1,0 s/p** | 430 |

Comparaison directe sur `PERFECT.pdf` (le même document, les deux moteurs) :

| | RapidOCR | Mistral OCR |
| --- | --- | --- |
| Titres | `FONCTIONNALITESGENERALES` | `# FONCTIONNALITÉS GÉNÉRALES` |
| Corps de texte | `Gestion delaclientele` | `Gestion de la clientèle` |
| Accents corrects | 54 | **73** |
| Durée | 266 s | **14,5 s** |

Conclusions établies par la mesure :

1. **Le volume n'est plus un enjeu.** Le débit s'améliore avec le nombre de
   pages (1 s/page sur 24 pages). Les ~90 pages du corpus se traitent en quelques
   minutes, contre ~2 h 30 estimées pour l'OCR local.
2. **Un document de 11,1 Mo passe sans erreur** en base64. Le risque de limite de
   taille ne concerne donc que `INTEROPERABILITE.pdf` (89 Mo).
3. **La qualité française est au rendez-vous** : structure markdown en titres,
   accents corrects, listes de fonctionnalités complètes et ordonnées.

Deux défauts constatés, à traiter dans le pipeline :

- **Artefacts LaTeX sur les puces graphiques** : `\(\odot\)`, `\(\mathbb{O}\)`
  apparaissent à la place des icônes de liste. Nettoyage par expression régulière
  en post-traitement.
- **Le contenu des infographies n'est pas transcrit.** Sur `PERFECT.pdf`, la
  section `# COUVERTURE FONCTIONNELLE` ne contient que trois références
  `![img-N.jpeg]`. L'information portée par les schémas est perdue. Sur ce
  document précis la perte est limitée — la section `FONCTIONNALITÉS GÉNÉRALES`
  qui suit rétablit la liste en texte — mais ce n'est pas garanti ailleurs.
  C'est précisément ce que le point de contrôle humain (4.4) doit détecter, en
  priorisant les pages dont le ratio références d'images / texte est élevé.

Quelques coquilles OCR résiduelles ont aussi été relevées (`rapportes` pour
`rapports`, `budgêtaire`, `ARCHITECHTURE`, `ratios prudents` pour
`ratios prudentiels`). Elles sont rares et sans effet notable sur la recherche
sémantique, mais justifient la relecture de l'étape 4.4.

## 4. Architecture du pipeline

Cinq étapes, avec un **point de contrôle humain** entre l'extraction et la
vectorisation.

```
Drive ──▶ [1] fetch ──▶ [2] dédup/filtre ──▶ [3] extraction routée
                                                     │
                                          documents/plaquettes_md/*.md
                                                     │
                                            [4] RELECTURE HUMAINE
                                                     │
                                    [5] fiches + chunks + embeddings ──▶ Supabase
```

Chaque étape est un module autonome, exécutable seul, avec une entrée et une
sortie sur disque. On peut donc rejouer l'étape 5 sans refaire l'OCR.

### 4.1 `src/ingestion/fetch_drive.py`

Télécharge les fichiers du Drive vers `documents/plaquettes/`.

- Liste `(id_drive, nom_fichier)` figée dans le module (le dossier est public).
- Vérifie l'intégrité par la présence du marqueur `%%EOF` en fin de fichier.
- Reprend les téléchargements incomplets. Cette garde n'est pas théorique :
  `INTEROPERABILITE.pdf` (89 Mo) et `SYCEBNL_CAGECFI.pdf` sont arrivés tronqués
  lors de l'audit.

### 4.2 `src/ingestion/audit_corpus.py`

Produit `documents/plaquettes_audit.json` :

```python
class DocumentAudit(BaseModel):
    """Résultat de l'audit d'extractibilité d'un PDF."""

    filename: str
    md5: str
    pages: int
    chars_per_page: int
    kind: Literal["TEXTE", "MIXTE", "IMAGE"]
    is_duplicate_of: Optional[str]
    language: Literal["fr", "en"]
    excluded_reason: Optional[str]
```

Décide, pour chaque document, s'il est retenu et par quelle voie il sera extrait.
L'exclusion est **explicite et tracée**, jamais silencieuse.

### 4.3 `src/ingestion/extract.py`

Routage dicté par l'audit :

- `kind == "TEXTE"` ou `"MIXTE"` → `DocumentConverter` avec `do_ocr = False`
- `kind == "IMAGE"` → Mistral OCR (`mistral-ocr-latest`)

Post-traitement appliqué à la sortie Mistral, motivé par les défauts mesurés en
3.3 :

- suppression des artefacts LaTeX de puces (`\(\odot\)`, `\(\mathbb{O}\)`) ;
- comptage des références `![img-N.jpeg]` par page, reporté en métadonnée
  `image_ratio` pour prioriser la relecture des pages riches en infographies.

Sortie : un fichier markdown par document dans `documents/plaquettes_md/`, avec
un en-tête YAML conservant la provenance :

```yaml
---
source_file: PERFECT.pdf
extraction: mistral_ocr
ocr_confidence: 0.94
pages: 4
extracted_at: 2026-07-31
---
```

Gestion d'erreurs, conforme aux conventions du projet : un échec sur un document
est journalisé et n'interrompt pas le traitement des autres. Les documents en
échec sont listés en fin d'exécution.

Point à valider à l'implémentation : `INTEROPERABILITE.pdf` fait 89 Mo et peut
dépasser la limite par requête de l'API. Prévoir un découpage par pages en
secours. Le plafond exact reste inconnu (documentation rendue en JavaScript),
mais un envoi de 11,1 Mo a été validé par appel réel (3.3) : seul ce fichier est
concerné.

### 4.4 Point de contrôle humain

Le markdown est un artefact **relisible et versionné dans git**. Avec 94 % du
contenu issu d'un OCR, une erreur détectée ici se corrige dans un fichier texte ;
détectée après vectorisation, elle impose de tout ré-ingérer.

Contrôles attendus : noms de produits, listes de fonctionnalités, chiffres et
coordonnées. Les pages dont le score de confiance OCR est faible sont signalées
en priorité.

### 4.5 `src/ingestion/enrich.py`

Pour chaque document, extraction d'une fiche produit structurée par le LLM déjà
configuré dans le projet :

```python
class ProductSheet(BaseModel):
    """Fiche de synthèse d'un produit ou d'une offre CAGECFI."""

    product: str
    category: Literal[
        "core_banking", "finance_digitale", "cloud", "fiscalite",
        "secteur_public", "gestion_metier", "corporate",
    ]
    target_audience: list[str]
    features: list[str]
    benefits: list[str]
    summary: str
```

La fiche est indexée **en plus** des chunks bruts. Justification : à la question
« que fait Perfect-Vision ? », une fiche de synthèse répond mieux qu'un fragment
de plaquette isolé, tandis que les chunks bruts restent nécessaires pour les
questions de détail.

### 4.6 `src/ingestion/ingest_supabase.py` (modifié)

- Purge des tables `cagecfi_documents` et `cagecfi_chunks` (remplacement complet
  de la base issue du crawl, décision de cadrage validée).
- Chunking du markdown, génération des embeddings, insertion.
- Métadonnées portées dans le champ `metadata` JSONB existant :

```json
{
  "product": "PERFECT",
  "category": "core_banking",
  "extraction": "mistral_ocr",
  "ocr_confidence": 0.94,
  "source_file": "PERFECT.pdf",
  "doc_type": "chunk"
}
```

`doc_type` vaut `chunk` ou `product_sheet`, ce qui permet de pondérer ou filtrer
les fiches de synthèse au moment de la recherche.

Le schéma SQL existant convient sans modification : `metadata` est déjà un JSONB,
et les index HNSW et GIN full-text français sont en place.

## 5. Taxonomie produits

Utilisée pour la métadonnée `category` :

| Catégorie | Documents |
| --- | --- |
| `corporate` | Qui sommes-nous, Visuel CAGECFI, Présentation/Insertion |
| `core_banking` | PERFECT, PERFECT-VISION-SIG, Modules réglementaires BIC/LBCFT |
| `finance_digitale` | Solutions de finance digitale, Interopérabilité, Processus Crédit JIWAY |
| `secteur_public` | Livret Solutions étatiques, GOV MONITOR |
| `fiscalite` | PAY TAX, Plaquette Fiscalisation |
| `cloud` | CLOUD_Administrations, CLOUD_SFD_IMF |
| `gestion_metier` | ERP COMPTA, GOMISE, IMMOS, SICOM, TRADER, SYCEBNL |

## 6. Configuration

Ajout dans `.env` et dans `src/settings_supabase.py` :

```bash
MISTRAL_API_KEY=...
MISTRAL_OCR_MODEL=mistral-ocr-latest
```

Mistral OCR n'est appelé qu'à l'ingestion locale. Aucune dépendance nouvelle ne
doit remonter dans le runtime Vercel : le client Mistral va dans l'extra
`[ingestion]` de `pyproject.toml`, aux côtés de Docling et Whisper.

## 7. Tests

Conformément aux conventions du projet, les tests reflètent l'arborescence source.

**Unitaires** (`tests/ingestion/`), sans appel réseau :

- `test_audit_corpus.py` — la classification TEXTE/MIXTE/IMAGE respecte les
  seuils ; les doublons MD5 sont détectés ; les documents anglais sont exclus
  avec un motif renseigné.
- `test_extract.py` — le routage envoie bien les `IMAGE` vers Mistral et les
  `TEXTE` vers Docling (client Mistral simulé) ; un échec sur un document
  n'interrompt pas la boucle.
- `test_enrich.py` — validation du modèle `ProductSheet` ; une réponse LLM
  malformée est rejetée sans faire tomber le pipeline.

**Intégration** (`-m integration`, exécution manuelle) :

- un appel réel à Mistral OCR sur `CLOUD_Administrations.pdf`, dont on connaît
  le contenu attendu (« Votre infrastructure numérique au cœur du Cloud ») ;
- une ingestion complète vers une base Supabase de test, puis une recherche
  hybride sur « fonctionnalités de Perfect » vérifiant que les résultats portent
  bien `product == "PERFECT"`.

**Critère de recette** : après ingestion, chaque document retenu compte au moins
un chunk non vide. Un document à zéro chunk est une erreur bloquante — c'est
exactement le mode de défaillance silencieuse identifié à la section 2.2.

## 8. Risques

| Risque | Statut | Traitement |
| --- | --- | --- |
| **Contenu des infographies non transcrit** | avéré (3.3) | Priorisation de la relecture via `image_ratio` ; recours à une description d'image seulement si la relecture révèle une perte réelle |
| Coquilles OCR résiduelles | avéré, marginal | Relecture 4.4 ; sans effet notable sur la recherche sémantique |
| Artefacts LaTeX sur les puces | avéré | Nettoyage par expression régulière (4.3) |
| `INTEROPERABILITE.pdf` (89 Mo) au-delà de la limite API | non levé | Découpage par pages en secours. Un document de 11,1 Mo passe sans erreur (3.3) : le risque ne concerne que ce fichier |
| Perte des pages du site (contact, actualités) | accepté | Coordonnées déjà en dur dans le prompt système |
| Plaquettes mises à jour ultérieurement | — | Pipeline rejouable de bout en bout ; markdown versionné |
| Coût et durée du traitement | levé | ~90 pages à 1–5 s/page, soit quelques minutes par exécution complète |

## 9. Hors périmètre

- Support bilingue du chatbot (les plaquettes anglaises sont exclues).
- Modification du prompt système ou de la logique de recherche hybride.
- Ingestion du fichier `Insertion 21,5 x 27,5_page-0001.jpg` (doublon image de la
  plaquette PDF correspondante).
- Re-crawl de `cagecfi.com` : la base issue du site est remplacée, pas fusionnée.
