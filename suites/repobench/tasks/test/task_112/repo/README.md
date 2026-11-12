# Search Projections

Documents have a nonempty string key/title and string body. Search is a case-insensitive intersection
 of whitespace-separated word tokens (letters/digits only); repeated words count once per document.
 Replacing a document removes obsolete terms, and deletion removes all postings. Facets count documents
 containing each term, not token occurrences. Validation failures must leave document storage and index
 projections unchanged. Empty queries return no results; export order is by document key.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
