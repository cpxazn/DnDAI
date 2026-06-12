from pathlib import Path

from backend.app.db.session import get_connection, initialize_database
from backend.app.schemas.campaigns import CampaignCreateRequest
from backend.app.schemas.characters import CharacterCreateRequest, CharacterUpdateRequest, WeaponLoadout, WeaponProfile
from backend.app.services.campaign_service import create_campaign
from backend.app.services.character_service import create_character, update_character


def test_update_character_can_set_structured_weapon_profile_and_ability_modifiers(tmp_path: Path):
    database_path = tmp_path / "character-update.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
            ),
        )

        updated = update_character(
            connection,
            campaign_id=campaign.id,
            character_id="pc_aric",
            payload=CharacterUpdateRequest(
                proficiency_bonus=3,
                ability_modifiers={"STR": 4, "DEX": 1},
                equipped_weapon=WeaponProfile(
                    name="Longsword",
                    damage_dice="1d8",
                    attack_ability="STR",
                    proficient=True,
                ),
            ),
        )

        assert updated is not None
        assert updated.proficiency_bonus == 3
        assert updated.ability_modifiers["STR"] == 4
        assert updated.equipped_weapon is not None
        assert updated.equipped_weapon.name == "Longsword"


def test_update_character_can_clear_equipped_weapon(tmp_path: Path):
    database_path = tmp_path / "character-update-clear.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                equipped_weapon=WeaponProfile(
                    name="Longsword",
                    damage_dice="1d8",
                ),
            ),
        )

        updated = update_character(
            connection,
            campaign_id=campaign.id,
            character_id="pc_aric",
            payload=CharacterUpdateRequest(clear_equipped_weapon=True),
        )

        assert updated is not None
        assert updated.equipped_weapon is None


def test_update_character_can_store_structured_weapon_loadout(tmp_path: Path):
    database_path = tmp_path / "character-loadout.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
            ),
        )

        updated = update_character(
            connection,
            campaign_id=campaign.id,
            character_id="pc_aric",
            payload=CharacterUpdateRequest(
                weapon_loadout=WeaponLoadout(
                    primary=WeaponProfile(name="Longsword", damage_dice="1d8", attack_ability="STR"),
                    ranged=WeaponProfile(name="Longbow", damage_dice="1d8", attack_ability="DEX", ranged=True),
                    active_slot="ranged",
                )
            ),
        )

        assert updated is not None
        assert updated.weapon_loadout is not None
        assert updated.weapon_loadout.active_slot == "ranged"
        assert updated.weapon_loadout.ranged is not None
        assert updated.weapon_loadout.ranged.name == "Longbow"
        assert updated.equipped_weapon is not None
        assert updated.equipped_weapon.name == "Longbow"
