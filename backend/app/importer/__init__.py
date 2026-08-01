"""Migrating ZMB's existing corpus into Reticle.

This package is an operator tool, not part of the served application. Nothing in
``app`` imports it, and it is only ever run by hand from the command line.

It is written to one rule: **never guess**. Every field, bullet colour, flag,
shape and media type it meets is either in a mapping table that was derived from
a census of the live corpus, or it is reported as unmapped and the run stops.
A migration that silently drops the one thing it did not recognise is worse than
one that refuses to finish, because the loss is only discovered years later by
somebody following a procedure with a step missing from it.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""
