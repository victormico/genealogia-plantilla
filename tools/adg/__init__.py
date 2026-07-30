"""The catalogue of a diocesan archive that serves it as JSON, and its images.

Written against the Arxiu Diocesà de Girona, whose web catalogue is an Angular
app in an iframe that hangs -- clicks that do not open, a form that empties
itself -- over four small JSON calls that work perfectly.

    session.py    the fetching: paced, cached forever, HEAD for probing
    catalog.py    the four calls, and the one field that decides everything
    images.py     the S3 URL pattern, and finding a book's end by bisection
    browse.py     the command line

Read this before using it, because it is the whole design:

**`bucket` is the field that decides whether you can read a book from home.**
The catalogue describes books it does not have images for, so the fiche existing
proves nothing. `catalog.Udoc.readable` is that check plus `condicions_acces`,
and `why_not()` says which one failed.

**This is a tool for consulting, not for harvesting.** The archive publishes no
API and no rate limit, which is a reason to be more careful and not less: it
paces itself, caches everything so a repeat costs nothing, and `images.py`
refuses to pull a whole book in one go. Download the eight pages you need. The
archive permits copies for personal use and charges rights for republication.
"""
