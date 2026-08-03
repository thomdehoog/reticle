"""The one clause that keeps a staff guide off a viewer's screen.

A guide carries two independent facts about who may read it. ``status`` says
whether it is finished — a draft is nobody's business but its author's — and
``visibility`` says who it was finished *for*. This module owns the second, and
it exists as its own file for the same reason ``PUBLISHED`` is a named constant:
the rule is one line, it has to be identical everywhere, and the places that
have to apply it are not in one router.

**It is a ``WHERE`` clause, never a filter applied afterwards.** A staff guide
that reaches the serialiser has already been loaded, and every later branch is
somewhere the rule can be forgotten — a search result assembled in a
comprehension, a tag count, a snapshot written to disk. Narrowing the statement
instead means the row never arrives, so there is nothing left to leak.

**A viewer is told the guide does not exist, not that it is off-limits.** The
detail endpoint answers 404 rather than 403, because a 403 confirms that a guide
with that address exists — and the address is the title, so confirming it
discloses that the facility has a procedure for whatever the reader guessed at.

An author and an administrator see everything, as they always have: they are the
people who write the staff guides.

**A reader who is not signed in is held to the same rule.** The corpus is
public — a login exists to decide who may change a guide, not who may read one —
so ``user`` here may be ``None``, and ``None`` is the most restricted caller
there is rather than an unhandled case.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from typing import TypeVar

from .models import EVERYONE, ROLE_RANK, Guide, User

Statement = TypeVar("Statement")

AUTHOR_RANK = ROLE_RANK["author"]


def sees_unpublished(user: User | None) -> bool:
    """Whether this caller sees anything beyond the finished, public corpus.

    One predicate for both halves of the question, because they have always had
    the same answer: an author or an administrator sees drafts *and* staff
    guides, and everybody else sees neither. It used to be spelled two ways —
    ``sees_staff_guides`` here, and ``user.role == "viewer"`` at nine call sites
    — which are exact complements of each other, so the two could disagree only
    by drifting.

    ``None`` is a reader who is not signed in, and it answers ``False``. That is
    the line that keeps the public site from widening anything: an anonymous
    caller is held to exactly what a viewer is held to, through the same test,
    rather than through a second rule written for them.
    """
    return user is not None and ROLE_RANK[user.role] >= AUTHOR_RANK


def readable_guides(statement: Statement, user: User | None) -> Statement:
    """Narrow any statement that selects guides to the ones *user* may read.

    Applied to the statement rather than to its results, and applied by every
    route that can return a guide — listing, search, tag counts, the detail
    endpoint. The sweep in ``tests/test_guide_visibility.py`` enumerates those
    routes and fails when a new one appears without it.
    """
    if sees_unpublished(user):
        return statement
    return statement.where(Guide.visibility == EVERYONE)
