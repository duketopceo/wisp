//! [POINT:x,y:label] extraction + screenshot→logical coord mapping —
//! parity with dim/points.py (canonical grammar documented there).
use serde_json::{json, Value};
use std::process::Command;

const MAX_POINTS: usize = 32;
const MAX_LABEL: usize = 80;

fn add(points: &mut Vec<Value>, x: i64, y: i64, label: &str) {
    if points.len() >= MAX_POINTS {
        return;
    }
    points.push(json!({"x": x, "y": y,
        "label": label.trim().chars().take(MAX_LABEL)
            .collect::<String>()}));
}

/// Extract `[POINT:x,y:label]` / `[POINTS:[{x,y,label}]]` tags.
/// Returns (clean_text, points in screenshot-pixel coords).
pub fn extract(text: &str) -> (String, Vec<Value>) {
    let mut points = Vec::new();
    let mut clean = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(i) = rest.find("[POINT") {
        let (before, tag) = rest.split_at(i);
        clean.push_str(before);
        // not a tag unless the next char is ':', ' ', ']' or 'S'
        match tag.as_bytes().get(6) {
            Some(b) if b": ]S".contains(b) => {}
            Some(_) => {
                clean.push_str(&tag[..6]);
                rest = &tag[6..];
                continue;
            }
            None => {
                clean.push_str(tag);
                rest = "";
                continue;
            }
        }
        if tag.starts_with("[POINTS") {
            match tag.find("]]") {
                Some(e) => {
                    // inner JSON array spans from the '[' after the
                    // prefix colon to the ']' at e
                    // find ':' after the "[POINTS" prefix, then the
                    // '[' that starts the JSON array
                    if let Some(a) = tag[1..e + 1].find(':')
                        .map(|o| o + 1)
                        .and_then(|c| tag[c..e + 1].find('[')
                            .map(|o| c + o))
                    {
                        if let Ok(Value::Array(items)) =
                            serde_json::from_str::<Value>(&tag[a..e + 1])
                        {
                            for p in items {
                                if let (Some(x), Some(y)) =
                                    (p["x"].as_i64(), p["y"].as_i64())
                                {
                                    add(&mut points, x, y,
                                        p["label"].as_str()
                                            .unwrap_or(""));
                                }
                            }
                        }
                    }
                    rest = &tag[e + 2..];
                }
                None => {
                    clean.push_str(tag);  // unclosed — leave visible
                    rest = "";
                }
            }
            continue;
        }
        // "[POINT:x,y:label]"
        match tag.find(']') {
            Some(e) => {
                let body = tag[6..e]
                    .trim_start_matches(|c| c == ':' || c == ' ');
                let (coords, label) = body.split_once(':')
                    .unwrap_or((body, ""));
                let mut xy = coords.split(',');
                if let (Ok(x), Ok(y)) =
                    (xy.next().unwrap_or("").trim().parse::<i64>(),
                     xy.next().unwrap_or("").trim().parse::<i64>())
                {
                    add(&mut points, x, y, label);
                }
                rest = &tag[e + 1..];
            }
            None => {
                clean.push_str(tag);  // unclosed — leave visible
                rest = "";
            }
        }
    }
    clean.push_str(rest);
    (clean.trim().to_string(), points)
}

/// hyprctl monitors -j → Vec of {x,y,width,height,scale}.
pub fn monitors() -> Vec<Value> {
    let Ok(Some(out)) = crate::util::run_timeout(
        Command::new("hyprctl").args(["monitors", "-j"]), 5)
    else {
        return Vec::new();
    };
    if !out.status.success() {
        return Vec::new();
    }
    serde_json::from_str(&String::from_utf8_lossy(&out.stdout))
        .unwrap_or_default()
}

/// Screenshot pixels → Hyprland logical coords. grim composites each
/// output at (logical_pos * scale); later outputs overwrite earlier on
/// overlap, so containment is checked last-to-first.
pub fn to_logical(points: &[Value], mons: &[Value]) -> Vec<Value> {
    points.iter().map(|p| {
        let x = p["x"].as_i64().unwrap_or(0) as f64;
        let y = p["y"].as_i64().unwrap_or(0) as f64;
        for m in mons.iter().rev() {
            let raw = m["scale"].as_f64().unwrap_or(1.0);
            let s = if raw > 0.0 { raw } else { 1.0 };
            let (mx, my) = (m["x"].as_f64().unwrap_or(0.0),
                            m["y"].as_f64().unwrap_or(0.0));
            let (ox, oy) = (mx * s, my * s);
            let (w, h) = (m["width"].as_f64().unwrap_or(0.0),
                          m["height"].as_f64().unwrap_or(0.0));
            if x >= ox && x < ox + w && y >= oy && y < oy + h {
                // floor(v+0.5) — same rounding rule as Python
                return json!({
                    "x": (mx + ((x - ox) / s + 0.5).floor()) as i64,
                    "y": (my + ((y - oy) / s + 0.5).floor()) as i64,
                    "label": p["label"]});
            }
        }
        p.clone()
    }).collect()
}
