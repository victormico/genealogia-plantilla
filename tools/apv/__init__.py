"""The index of the Arxiu Parroquial de València: coverage, queries, fiches.

    coverage.py   what years each parish is indexed for -- ask this FIRST, it is
                  free and it stops you spending a query on a gap
    query.py      builds the search URLs (latin-1, see the note there)
    session.py    the fetching, and the pace that governs it
    parse.py      a results page -> fiche records -> a .md transcription
    verify.py     the bottom-up verification worklist

There is no confirmed daily limit on this archive -- a "fifteen queries a day"
figure circulated for a while but turned out to trace back to an unverified
secondhand claim, not the site itself; see tools/apv/session.py for the full
story. The quota in session.py is a courtesy pace you set yourself, persistent
and reconciled against whatever the archive's own pages say, if they ever say
anything; read its docstring before changing anything about how requests are
made.
"""
