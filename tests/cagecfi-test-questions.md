# Jeu de tests — Agent support CAGECFI

Questions de référence pour valider l'agent. Les réponses attendues proviennent de la base de connaissances (FAQ, pages crawlées de cagecfi.com, fiche services).

**Comment l'utiliser :** posez chaque question à l'agent (CLI ou Web), comparez à la réponse attendue, et notez le résultat dans la colonne **OK ?** (✅ / ❌). Si une réponse est fausse ou « je n'ai pas trouvé » alors que l'info existe, enrichissez [`documents/cagecfi-faq.md`](../documents/cagecfi-faq.md) puis relancez l'ingestion.

---

## 1. Présentation de l'entreprise

| # | Question | Réponse attendue (résumé) | OK ? |
|---|----------|---------------------------|------|
| 1 | Qu'est-ce que CAGECFI ? | Société spécialisée dans la gestion intégrée des systèmes financiers décentralisés et la transformation numérique, créée en 2001 à Lomé (Togo). | |
| 2 | En quelle année CAGECFI a-t-elle été créée ? | En 2001, à Lomé. | |
| 3 | CAGECFI est-elle certifiée ? | Oui, certifiée ISO 9001:2015. | |
| 4 | Dans quels pays CAGECFI est-elle présente ? | Togo, Bénin, Burkina Faso, Niger, Côte d'Ivoire ; partenariats avec la France. | |
| 5 | Où se trouve le siège de CAGECFI ? | À Lomé, au Togo. | |

## 2. Contact

| # | Question | Réponse attendue (résumé) | OK ? |
|---|----------|---------------------------|------|
| 6 | Comment contacter CAGECFI ? | Email cagecfi@cagecfi.com, téléphone +228 22 26 84 61, siège à Lomé (Togo). | |
| 7 | Quelle est l'adresse email de CAGECFI ? | cagecfi@cagecfi.com (et cagecfibenin@cagecfi.com pour le Bénin). | |
| 8 | Quel est le numéro de téléphone de CAGECFI ? | +228 22 26 84 61. | |
| 9 | CAGECFI a-t-elle un bureau au Bénin ? | Oui, à Cotonou (Fidjrossè Kpota), email cagecfibenin@cagecfi.com. | |

## 3. Produits et solutions

| # | Question | Réponse attendue (résumé) | OK ? |
|---|----------|---------------------------|------|
| 10 | Qu'est-ce que Perfect-Vision ? | Le logiciel phare de CAGECFI : gestion intégrée des systèmes financiers décentralisés (SFD). | |
| 11 | Quelles fonctionnalités offre Perfect-Vision ? | Clientèle, crédit, épargne, tontine, comptabilité, RH/paie, immobilisations, stock, finance digitale, états financiers, etc. | |
| 12 | Quelles solutions de finance digitale propose CAGECFI ? | E-banking, mobile banking, SMS banking, mobile money, mobile agency, transfert d'argent, monétique. | |
| 13 | CAGECFI a-t-elle des solutions pour les États / administrations ? | Oui : SIFEN, SIGEP, télédéclaration d'impôt, PAY'TAX, SIG-M, SIG-IFI. | |
| 14 | Avez-vous une solution pour les ONG et associations ? | Oui, SYCEBNL-ERP (conformité et transparence financière). | |
| 15 | CAGECFI accompagne-t-elle l'interopérabilité PI-SPI de la BCEAO ? | Oui, via une cellule dédiée PI-SPI ; contact cagecfi@cagecfi.com. | |
| 16 | Perfect-Vision gère-t-il la finance islamique ? | Oui, c'est une des fonctionnalités. | |
| 17 | Proposez-vous une solution de transfert d'argent ? | Oui, plateforme web et mobile de transfert d'argent. | |

## 4. Devis, démonstration et tarifs

| # | Question | Réponse attendue (résumé) | OK ? |
|---|----------|---------------------------|------|
| 18 | Comment demander un devis ? | Via la page « Demander un devis » du site, ou par email à cagecfi@cagecfi.com. | |
| 19 | Comment obtenir une démonstration de Perfect-Vision ? | Demander via le site ou par email cagecfi@cagecfi.com en précisant ses besoins. | |
| 20 | Quels sont les tarifs des solutions CAGECFI ? | Les tarifs dépendent du périmètre ; demander un devis (pas de prix fixe communiqué). | |

## 5. Formation et recrutement

| # | Question | Réponse attendue (résumé) | OK ? |
|---|----------|---------------------------|------|
| 21 | CAGECFI propose-t-elle des formations ? | Oui, via CAGECFI Academy (transition numérique, capacités managériales). | |
| 22 | Comment faire une demande de formation ? | Depuis la page « Demande de formation » du site www.cagecfi.com. | |
| 23 | CAGECFI recrute-t-elle ? | Oui, opportunités sur la page « Recrutement » du site. | |

## 6. Support

| # | Question | Réponse attendue (résumé) | OK ? |
|---|----------|---------------------------|------|
| 24 | J'ai un problème technique avec ma solution, que faire ? | Contacter le support : cagecfi@cagecfi.com ou +228 22 26 84 61, en décrivant le problème. | |

## 7. Salutations (ne doivent PAS déclencher de recherche)

| # | Question | Réponse attendue (résumé) | OK ? |
|---|----------|---------------------------|------|
| 25 | Bonjour | Salutation en retour + proposition d'aide, sans recherche. | |
| 26 | Merci ! | Réponse de politesse, sans recherche. | |

## 8. Hors périmètre (l'agent doit décliner sans inventer)

| # | Question | Réponse attendue (résumé) | OK ? |
|---|----------|---------------------------|------|
| 27 | Quelle est la capitale de la France ? | Indiquer qu'il n'a pas cette information / hors de son périmètre CAGECFI. | |
| 28 | Quel temps fera-t-il demain à Lomé ? | Décliner : information non disponible dans la documentation CAGECFI. | |
| 29 | Peux-tu me donner le numéro personnel du directeur ? | Décliner : information non disponible ; rediriger vers le contact officiel. | |
| 30 | Quel est le chiffre d'affaires de CAGECFI en 2024 ? | Décliner si l'info n'est pas dans la base (ne pas inventer de chiffre). | |

---

### Critères de réussite
- **Exactitude** : la réponse correspond aux faits ci-dessus (emails, téléphone, produits corrects).
- **Ancrage** : aucune invention (procédures, chiffres, contacts non listés).
- **Périmètre** : les questions hors sujet (section 8) sont déclinées poliment.
- **Langue** : réponses en français, claires et concises.
