---
title: Ús i flux de treball — DiscScope
layout: default
---

# Ús i flux de treball

## Arrencar sense base de dades

Si encara no hi ha cap fitxer de base de dades, l'app mostra una pantalla de benvinguda amb un enllaç a **Discs**. Des de **Discs** pots auditar la primera carpeta o disc i es crearà la base de dades automàticament.

## Gestió de discs

### Incorporar un disc nou

1. Ves a **Discs**.
2. Indica la **carpeta o disc a auditar** (p. ex. `D:\` o `E:\backups`).
3. Indica un **identificador del disc** (p. ex. `EXT-A`, `HDD1`). Aquest nom servirà per filtrar i identificar el disc a tot l'app.
4. Enviar el formulari. L'app recorre la carpeta i escriu directament a la base de dades (sense CSV intermedis).

En discs molt grans (p. ex. 5–8 TB amb molts fitxers), el procés pot dur diversos minuts.

### Actualitzar un disc existent

1. Marca **Substituir dades d'aquest disc**.
2. Indica el **mateix identificador** (*drive_id*) que vas fer servir abans.
3. Indica la nova ruta (o la mateixa si has tornat a auditar).
4. Enviar. Les dades antigues d'aquest disc es substitueixen.

## Rutes principals

| Ruta | Descripció |
|------|-------------|
| **Inici** | Si hi ha DB: resum per disc, top extensions, top carpetes. Si no: benvinguda. |
| **Cercar** | Cerca per paraula clau (nom o ruta); filtre opcional per disc. |
| **Duplicats** | Fitxers amb el mateix nom, o nom + mida, en més d'un disc. |
| **Extensions** | Estadístiques per extensió (paginat). |
| **Carpetes** | Llistat de carpetes per mida (paginat). |
| **Explorador** | Arbre de carpetes i fitxers des de la DB (sense accés al sistema de fitxers). |
| **Discs** | Auditar i incorporar o actualitzar discs. |

## Notes

- Les cerques i llistats grans fan servir **paginació** per no sobrecarregar la memòria.
- Les rutes que requereixen la base de dades retornen error **503** si la DB no existeix; **Inici** i **Discs** es carreguen sense DB.
