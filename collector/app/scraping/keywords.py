"""French / English giveaway keyword lists (phrase-first matching)."""

from __future__ import annotations

# Longer / more specific phrases first — matched before single tokens.
PHRASES_FR: tuple[str, ...] = (
    "jeu concours",
    "tirage au sort",
    "a gagner",
    "à gagner",
    "reglement du jeu",
    "règlement du jeu",
    "sans obligation d'achat",
    "sans obligation d achat",
    "participez maintenant",
    "tentez votre chance",
)

PHRASES_EN: tuple[str, ...] = (
    "enter now",
    "no purchase necessary",
    "official rules",
    "sweep stakes",
    "sweepstakes",
    "prize draw",
    "free entry",
)

KEYWORDS_FR: tuple[str, ...] = (
    "concours",
    "gagner",
    "gagnez",
    "remportez",
    "remporter",
    "cadeau",
    "participez",
    "participer",
    "participation",
    "loterie",
)

KEYWORDS_EN: tuple[str, ...] = (
    "giveaway",
    "giveaways",
    "sweepstake",
    "sweepstakes",
    "contest",
    "contests",
    "prize",
    "prizes",
    "competition",
    "competitions",
)

# Short ambiguous tokens: only count with word boundaries + lower weight.
WEAK_KEYWORDS_EN: tuple[str, ...] = (
    "win",
    "wins",
    "won",
    "enter",
)

DEADLINE_PHRASES: tuple[str, ...] = (
    "date limite",
    "closes on",
    "closing date",
    "ends on",
    "end date",
    "expire",
    "expires",
    "jusqu'au",
    "jusqu au",
    "avant le",
    "valid until",
    "deadline",
)

ENTRY_PHRASES: tuple[str, ...] = (
    "remplir le formulaire",
    "fill out the form",
    "fill in the form",
    "enter your email",
    "saisir votre email",
    "saisissez votre",
    "pour participer",
    "to enter",
    "how to enter",
    "comment participer",
    "inscription",
    "submit your entry",
)

TERMS_LINK_HINTS: tuple[str, ...] = (
    "reglement",
    "règlement",
    "terms",
    "rules",
    "conditions",
    "official rules",
    "modalites",
    "modalités",
)
