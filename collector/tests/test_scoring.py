"""Tests for candidate scoring heuristics."""

from __future__ import annotations

from app.scraping.scoring import score_candidate


def test_strong_french_giveaway_scores_high() -> None:
    result = score_candidate(
        url="https://brand.fr/jeu-concours/ete-2026",
        title="Grand jeu concours — tentez de gagner",
        content=(
            "Participez à notre jeu concours et remportez un cadeau. "
            "Tirage au sort le 30 juin. Date limite de participation. "
            "Sans obligation d'achat. Voir le règlement du jeu. "
            "Pour participer, remplissez le formulaire."
        ),
        link_texts=["Règlement", "Participer"],
    )
    assert result.score >= 0.45
    assert result.evidence.url_keyword or result.evidence.title_keyword
    assert result.evidence.content_strong_hits >= 2


def test_strong_english_giveaway_scores_high() -> None:
    result = score_candidate(
        url="https://brand.com/giveaway/summer",
        title="Win a prize — official giveaway",
        content=(
            "Enter now for our sweepstakes. Free entry. Official rules apply. "
            "Closing date 1 August. How to enter: fill out the form."
        ),
        link_texts=["Official Rules", "Enter now"],
    )
    assert result.score >= 0.45


def test_single_weak_keyword_is_not_enough() -> None:
    result = score_candidate(
        url="https://shop.example/products/laptop",
        title="Windows laptop sale",
        content="Buy this Windows machine and win friends with your productivity tips.",
    )
    assert result.score < 0.45


def test_product_prize_mention_false_positive() -> None:
    result = score_candidate(
        url="https://shop.example/catalog/prize-ribbon",
        title="Prize ribbon for sports day",
        content="Our prize ribbons are perfect for school competitions and events.",
    )
    assert result.score < 0.45


def test_cadeau_shop_alone_is_weak() -> None:
    result = score_candidate(
        url="https://boutique.example/cadeaux",
        title="Idées cadeau",
        content="Trouvez le cadeau idéal pour vos proches. Livraison rapide.",
    )
    assert result.score < 0.45


def test_news_article_about_contest_law_not_auto_candidate() -> None:
    result = score_candidate(
        url="https://news.example/articles/regulation",
        title="New regulation on contests",
        content="Lawmakers discussed competition policy and market contests in parliament.",
    )
    assert result.score < 0.45
