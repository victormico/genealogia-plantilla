"""The index of the Arxiu Parroquial de València: coverage, queries, fiches.

    coverage.py   what years each parish is indexed for -- ask this FIRST, it is
                  free and it stops you spending a query on a gap
    query.py      builds the search URLs (latin-1, see the note there)
    session.py    the fetching, and the daily quota that governs it
    parse.py      a results page -> fiche records -> a .md transcription
    verify.py     the bottom-up verification worklist

The archive rations non-members to fifteen queries a day. The quota in
session.py is persistent and reconciles against the archive's own counter; read
its docstring before changing anything about how requests are made.
"""
