use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::LazyLock;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LogEventKind {
    ZoneEnter,
    WhoZone,
    WhoSelf,
    BindConfirm,
    CharinfoBind,
    LevelUp,
    VeliumVapors,
    Fte,
    MobKill,
    YouSlain,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogEvent {
    pub kind: LogEventKind,
    pub character: Option<String>,
    pub zone: Option<String>,
    pub detail: Option<String>,
    pub mob: Option<String>,
    pub player: Option<String>,
    pub slayer: Option<String>,
    pub eq_log_time: Option<String>,
    pub level: Option<u32>,
    pub class_name: Option<String>,
}

pub struct LogPatterns {
    zone_enter: Regex,
    who_zone: Regex,
    who_self: Regex,
    charinfo_bind: Regex,
    bind_confirm: Regex,
    level_up: Regex,
    velium_vapors: Regex,
    fte: Regex,
    you_slain: Regex,
    mob_slain: Regex,
}

static RAID_TARGETS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "a broken golem",
        "a dracoliche",
        "an angry goblin",
        "aaryonar",
        "casalen",
        "cazic thule",
        "cekenar",
        "dagarn the destroyer",
        "dain frostreaver iv",
        "derakor the vindicator",
        "dozekar the cursed",
        "dread",
        "druushk",
        "eashen of the sky",
        "essedera",
        "faydedar",
        "fright",
        "gorenaire",
        "gozzrem",
        "grozzmel",
        "guardian kozzalym",
        "hoshkar",
        "ikatiar the venom",
        "innoruuk",
        "jorlleag",
        "kelorek`dar",
        "keldor dek`torek",
        "king tormax",
        "klandicar",
        "krigara",
        "lady mirenilla",
        "lady nevederia",
        "lady vox",
        "lendiniara the keeper",
        "lepethida",
        "lodizal",
        "lord doljonijiarnimorinar",
        "lord feshlak",
        "lord kreizenn",
        "lord koi`doken",
        "lord nagafen",
        "lord vyemm",
        "lord yelinak",
        "master of the guard",
        "master yael",
        "midayor",
        "myga",
        "narandi the wretched",
        "nexona",
        "nillipuss",
        "noble dojorn",
        "phara dar",
        "phinigel autropos",
        "sevalak",
        "severilous",
        "silverwing",
        "sir lucan d`lere",
        "sontalak",
        "stormfeather",
        "talendor",
        "tavekalem",
        "telkorenar",
        "terror",
        "the final arbiter",
        "the progenitor",
        "the statue of rallos zek",
        "trakanon",
        "tunare",
        "vaniki",
        "velketor the sorcerer",
        "venril sathir",
        "verina tomb",
        "vessel drozlin",
        "vilefang",
        "vulak`aerr",
        "wraith of a shissir",
        "wuoshi",
        "xegony",
        "xygoz",
        "yelinak",
        "ymmeln",
        "zlandicar",
        "zlexak",
        "zordak ragefire",
    ]
    .into_iter()
    .collect()
});

pub fn is_raid_target(name: &str) -> bool {
    let lc = name.trim().to_lowercase();
    RAID_TARGETS.contains(lc.as_str())
}

pub fn character_from_log_path(path: &std::path::Path) -> Option<String> {
    let name = path.file_name()?.to_str()?;
    let stem = name.strip_suffix(".txt")?;
    let parts: Vec<&str> = stem.split('_').collect();
    if parts.len() >= 3 && parts[0] == "eqlog" {
        Some(parts[1].to_string())
    } else {
        None
    }
}

impl Default for LogPatterns {
    fn default() -> Self {
        let ts = r"\[(?P<time>\w{3} \w{3} \d{2} \d\d:\d\d:\d\d \d{4})\] +";
        Self {
            zone_enter: Regex::new(&format!(r"^{ts}You have entered (?P<zone>.*?)\.$")).unwrap(),
            who_zone: Regex::new(&format!(
                r"^{ts}There (?:are|is) (?P<num>\d+) players? in (?P<zone>.+?)\.$"
            ))
            .unwrap(),
            who_self: Regex::new(&format!(
                r"^{ts}\[(?P<level>\d+) (?P<klass>[\w ]+?)\] (?P<name>\w+) "
            ))
            .unwrap(),
            charinfo_bind: Regex::new(&format!(r"^{ts}You are currently bound in: (?P<zone>.*)"))
                .unwrap(),
            bind_confirm: Regex::new(&format!(r"^{ts}You feel yourself bind to the area\."))
                .unwrap(),
            level_up: Regex::new(&format!(
                r"^{ts}You have gained a level! Welcome to level (?P<level>\d+)!$"
            ))
            .unwrap(),
            velium_vapors: Regex::new(&format!(
                r"^{ts}Your Vial of Velium Vapors begins to glow\."
            ))
            .unwrap(),
            fte: Regex::new(&format!(r"^{ts}(?P<mob>.+?) engages (?P<player>\w+)!")).unwrap(),
            you_slain: Regex::new(&format!(r"^{ts}You have slain (?P<mob>.+?)!")).unwrap(),
            mob_slain: Regex::new(&format!(
                r"^{ts}(?P<mob>.+?) has been slain by (?P<slayer>.+?)!"
            ))
            .unwrap(),
        }
    }
}

impl LogPatterns {
    pub fn classify(&self, line: &str) -> LogEvent {
        if let Some(caps) = self.zone_enter.captures(line) {
            return LogEvent {
                kind: LogEventKind::ZoneEnter,
                character: None,
                zone: Some(caps["zone"].to_string()),
                detail: None,
                mob: None,
                player: None,
                slayer: None,
                eq_log_time: Some(caps["time"].to_string()),
                level: None,
                class_name: None,
            };
        }
        if let Some(caps) = self.who_zone.captures(line) {
            return LogEvent {
                kind: LogEventKind::WhoZone,
                character: None,
                zone: Some(caps["zone"].to_string()),
                detail: None,
                mob: None,
                player: None,
                slayer: None,
                eq_log_time: Some(caps["time"].to_string()),
                level: None,
                class_name: None,
            };
        }
        if let Some(caps) = self.who_self.captures(line) {
            return LogEvent {
                kind: LogEventKind::WhoSelf,
                character: Some(caps["name"].to_string()),
                zone: None,
                detail: None,
                mob: None,
                player: None,
                slayer: None,
                eq_log_time: Some(caps["time"].to_string()),
                level: caps["level"].parse().ok(),
                class_name: Some(caps["klass"].to_string()),
            };
        }
        if let Some(caps) = self.charinfo_bind.captures(line) {
            return LogEvent {
                kind: LogEventKind::CharinfoBind,
                character: None,
                zone: Some(caps["zone"].to_string()),
                detail: None,
                mob: None,
                player: None,
                slayer: None,
                eq_log_time: Some(caps["time"].to_string()),
                level: None,
                class_name: None,
            };
        }
        if let Some(caps) = self.bind_confirm.captures(line) {
            return LogEvent {
                kind: LogEventKind::BindConfirm,
                character: None,
                zone: None,
                detail: None,
                mob: None,
                player: None,
                slayer: None,
                eq_log_time: Some(caps["time"].to_string()),
                level: None,
                class_name: None,
            };
        }
        if let Some(caps) = self.level_up.captures(line) {
            return LogEvent {
                kind: LogEventKind::LevelUp,
                character: None,
                zone: None,
                detail: Some(caps["level"].to_string()),
                mob: None,
                player: None,
                slayer: None,
                eq_log_time: Some(caps["time"].to_string()),
                level: caps["level"].parse().ok(),
                class_name: None,
            };
        }
        if let Some(caps) = self.velium_vapors.captures(line) {
            return LogEvent {
                kind: LogEventKind::VeliumVapors,
                character: None,
                zone: None,
                detail: None,
                mob: None,
                player: None,
                slayer: None,
                eq_log_time: Some(caps["time"].to_string()),
                level: None,
                class_name: None,
            };
        }
        if let Some(caps) = self.fte.captures(line) {
            return LogEvent {
                kind: LogEventKind::Fte,
                character: None,
                zone: None,
                detail: None,
                mob: Some(caps["mob"].to_string()),
                player: Some(caps["player"].to_string()),
                slayer: None,
                eq_log_time: Some(caps["time"].to_string()),
                level: None,
                class_name: None,
            };
        }
        if let Some(caps) = self.you_slain.captures(line) {
            return LogEvent {
                kind: LogEventKind::YouSlain,
                character: None,
                zone: None,
                detail: None,
                mob: Some(caps["mob"].to_string()),
                player: None,
                slayer: None,
                eq_log_time: Some(caps["time"].to_string()),
                level: None,
                class_name: None,
            };
        }
        if let Some(caps) = self.mob_slain.captures(line) {
            return LogEvent {
                kind: LogEventKind::MobKill,
                character: None,
                zone: None,
                detail: None,
                mob: Some(caps["mob"].to_string()),
                player: None,
                slayer: Some(caps["slayer"].to_string()),
                eq_log_time: Some(caps["time"].to_string()),
                level: None,
                class_name: None,
            };
        }
        LogEvent {
            kind: LogEventKind::Unknown,
            character: None,
            zone: None,
            detail: None,
            mob: None,
            player: None,
            slayer: None,
            eq_log_time: None,
            level: None,
            class_name: None,
        }
    }

    pub fn tail_offset(content: &[u8]) -> usize {
        const MARKER: &[u8] = b"Welcome to EverQuest!";
        const WINDOW: usize = 1000;
        let start = content.len().saturating_sub(WINDOW);
        let slice = &content[start..];
        if let Some(pos) = slice.windows(MARKER.len()).rposition(|w| w == MARKER) {
            start + pos + MARKER.len()
        } else {
            content.len()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TS: &str = "[Wed Jul 30 12:00:00 2026] ";

    #[test]
    fn classify_bind_confirm() {
        let patterns = LogPatterns::default();
        let event = patterns.classify(&format!("{TS}You feel yourself bind to the area."));
        assert_eq!(event.kind, LogEventKind::BindConfirm);
    }

    #[test]
    fn classify_charinfo_bind() {
        let patterns = LogPatterns::default();
        let event = patterns.classify(&format!("{TS}You are currently bound in: Kael Drakkel"));
        assert_eq!(event.kind, LogEventKind::CharinfoBind);
        assert_eq!(event.zone.as_deref(), Some("Kael Drakkel"));
    }

    #[test]
    fn classify_who_self() {
        let patterns = LogPatterns::default();
        let event = patterns.classify(&format!(
            "{TS}[60 Cleric] Healername tells the guild, hello"
        ));
        assert_eq!(event.kind, LogEventKind::WhoSelf);
        assert_eq!(event.character.as_deref(), Some("Healername"));
        assert_eq!(event.level, Some(60));
        assert_eq!(event.class_name.as_deref(), Some("Cleric"));
    }

    #[test]
    fn classify_velium_vapors() {
        let patterns = LogPatterns::default();
        let event = patterns.classify(&format!("{TS}Your Vial of Velium Vapors begins to glow."));
        assert_eq!(event.kind, LogEventKind::VeliumVapors);
    }

    #[test]
    fn raid_targets_include_union_entries() {
        for name in [
            "wraith of a shissir",
            "xygoz",
            "ymmeln",
            "zlexak",
            "zordak ragefire",
            "xegony",
            "yelinak",
        ] {
            assert!(is_raid_target(name), "missing raid target: {name}");
        }
    }
}
