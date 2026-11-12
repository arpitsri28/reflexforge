# Dependency Container

The application accepts named provider definitions with kind, dependency names and option dictionaries.
 Resolve dependencies before constructing their dependent. A successful provider is shared by identity
 within one loader. A failed construction must be retried on a later resolve; completed dependencies may
 remain cached. Unknown names raise KeyError. Cycles raise DependencyCycle with the involved names.
 Factories receive resolved dependency objects and copied options. Independent applications are isolated.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
