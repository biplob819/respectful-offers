# N1.5 acceptance criteria

**DAT-03 — rules read, terms quoted, ruling recorded**
- `DATA_CARD.md` quotes the rules' Data Access and Use, Data Security and Public Code Sharing terms verbatim, links the rules page, and states the ruling as `OWNER D-46`; the decision log holds OWNER D-46; nothing in the data card is still marked pending.

**DAT-07 — real files downloaded and verified**
- `docs/data/kkbox-manifest.json` is the manifest `offers data verify` wrote for the real download (`source: kaggle`, all seven files with the competition's exact columns); its row counts and checksums are the ones the data card's table states; it holds no member data; when the real files are present locally, the local manifest is byte-identical to the committed one and still verifies.
