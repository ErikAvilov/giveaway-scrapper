"""Adapter registry — resolve by crawl_config.adapter key (no domain if-chains)."""

from __future__ import annotations

from app.scraping.adapters.base import SourceAdapter
from app.scraping.adapters.concours_du_net import ConcoursDuNetAdapter
from app.scraping.adapters.concours_fr import ConcoursFrAdapter
from app.scraping.adapters.contestgirl import ContestGirlAdapter
from app.scraping.adapters.echantillonsclub import EchantillonsClubAdapter
from app.scraping.adapters.giveario import GivearioAdapter
from app.scraping.adapters.gleam import GleamAdapter
from app.scraping.adapters.le_demon_du_jeu import LeDemonDuJeuAdapter
from app.scraping.adapters.mes_echantillons_gratuits import MesEchantillonsGratuitsAdapter
from app.scraping.adapters.online_competition import OnlineCompetitionAdapter
from app.scraping.adapters.prize_runner import PrizeRunnerAdapter
from app.scraping.adapters.the_prize_finder import ThePrizeFinderAdapter

_REGISTRY: dict[str, SourceAdapter] = {
    ConcoursDuNetAdapter.key: ConcoursDuNetAdapter(),
    LeDemonDuJeuAdapter.key: LeDemonDuJeuAdapter(),
    ConcoursFrAdapter.key: ConcoursFrAdapter(),
    MesEchantillonsGratuitsAdapter.key: MesEchantillonsGratuitsAdapter(),
    EchantillonsClubAdapter.key: EchantillonsClubAdapter(),
    GivearioAdapter.key: GivearioAdapter(),
    ThePrizeFinderAdapter.key: ThePrizeFinderAdapter(),
    OnlineCompetitionAdapter.key: OnlineCompetitionAdapter(),
    PrizeRunnerAdapter.key: PrizeRunnerAdapter(),
    ContestGirlAdapter.key: ContestGirlAdapter(),
    GleamAdapter.key: GleamAdapter(),
}


def get_adapter(key: str | None) -> SourceAdapter | None:
    if not key:
        return None
    return _REGISTRY.get(str(key).strip())


def registered_adapter_keys() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))
