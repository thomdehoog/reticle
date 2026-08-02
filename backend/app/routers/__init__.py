"""HTTP routers, one module per resource in the API contract.

Deliberately empty of imports. ``main`` names every router it mounts, and a
second list here is a second place for one to be forgotten — which is what
happened: four of the nine were missing, so ``from .routers import *`` would
have silently served a smaller API than the one that exists.
"""
