/*
  The filter calculator, the packing planner and the label numbering, for
  the web app and for the API other programs call (the filter-calculator
  Edge Function).

  This is the JavaScript twin of the desktop's Python modules:

      materials.py  filter_calc.py  bracing.py  mounting_frames.py
      packing.py    order_packing.py (weights)  delivery_labels.py (contract)

  and tests/test_calc_parity.py runs the same requests through both and
  fails if they disagree on anything, so a rule changed in one place and not
  the other cannot ship. The rules themselves are explained in those Python
  files; the comments here only cover what is different about JavaScript.

  One file, three ways in:
    - the web page loads it as a plain <script> and gets window.TAFCALC;
    - Node require()s it (the parity test);
    - the Edge Function imports it for its side effect, then reads
      globalThis.TAFCALC.
  supabase/functions/_shared/calc.js is a byte-for-byte copy, because an
  Edge Function can only bundle files under supabase/functions. A test
  holds the two copies identical.
*/
"use strict";

(function (root) {

  /* ── Numbers ──────────────────────────────────────────────────────── */

  function finite(v) {
    if (v === null || v === undefined || typeof v === "boolean") { return null; }
    if (typeof v === "string" && v.trim() === "") { return null; }
    var n = Number(v);
    return isFinite(n) ? n : null;
  }
  function positive(v) { var n = finite(v); return n !== null && n > 0 ? n : null; }
  function nonNegative(v) { var n = finite(v); return n !== null && n >= 0 ? n : null; }
  function positiveInt(v) {
    if (v === null || v === undefined || typeof v === "boolean") { return null; }
    if (typeof v === "number") {
      return isFinite(v) && Math.floor(v) === v && v >= 1 ? v : null;
    }
    var t = String(v).trim();
    if (/^\d+$/.test(t)) { var n = parseInt(t, 10); return n >= 1 ? n : null; }
    return null;
  }
  // Python's round(): halves go to the even neighbour. The worksheet has
  // always rounded this way, so the calculator must too.
  function pyRound(x) {
    var f = Math.floor(x), d = x - f;
    if (Math.abs(d - 0.5) < 1e-9) { return f % 2 === 0 ? f : f + 1; }
    return Math.round(x);
  }
  function round9(x) { return Math.round(x * 1e9) / 1e9; }
  function ceilTo(v, step) { return Math.ceil(round9(v / step)) * step; }
  function trimZeros(t) {
    t = String(t);
    if (t.indexOf(".") === -1) { return t; }
    t = t.replace(/0+$/, "").replace(/\.$/, "");
    return t || "0";
  }
  function fixed(v, n) { return v === null || v === undefined ? "" : v.toFixed(n); }
  function sum(arr) { return arr.reduce(function (a, b) { return a + b; }, 0); }
  function clone(o) { return o === undefined ? undefined : JSON.parse(JSON.stringify(o)); }

  /* ── Materials ────────────────────────────────────────────────────── */

  var DEFAULTS_VERSION = "TAF-MATERIALS-2026-10";
  var WIRE_CODES = ["LARGE_WIRE", "SMALL_WIRE"];
  var MEDIA_CODES = ["WASHABLE", "F5", "G4", "180", "GREY", "BLACK"];
  var DEFAULT_WIRE = {
    LARGE_WIRE: { mesh_opening_mm: [25, 25], wire_diameter_mm: 1.24,
                  roll_width_mm: 1200, roll_length_mm: 30000,
                  roll_weight_kg: 24.87, basis: "supplied_roll_mass" },
    SMALL_WIRE: { mesh_opening_mm: [12, 12], wire_diameter_mm: 0.80,
                  roll_width_mm: 1200, roll_length_mm: 30000,
                  roll_weight_kg: 19.30, basis: "supplied_roll_mass" }
  };
  var DEFAULT_MEDIA = {
    WASHABLE: { stock_weight_kg: 10.08, stock_area_m2: 42, basis: "supplied_stock_mass" },
    F5:       { stock_weight_kg: 14.70, stock_area_m2: 42, basis: "supplied_stock_mass" },
    G4:       { stock_weight_kg: 12.60, stock_area_m2: 42, basis: "supplied_stock_mass" },
    "180":    { stock_weight_kg: 15.12, stock_area_m2: 84, basis: "supplied_stock_mass" },
    GREY:     { stock_weight_kg: 12.60, stock_area_m2: 84, basis: "supplied_stock_mass" },
    BLACK:    { stock_weight_kg: null, stock_area_m2: 63,
                basis: "derived_from_GREY", derived_from: "GREY" }
  };
  Object.keys(DEFAULT_MEDIA).forEach(function (k) {
    DEFAULT_MEDIA[k].roll_width_mm = null;
    DEFAULT_MEDIA[k].roll_length_mm = null;
  });
  var MEDIA_ALIASES = { WASHABLE: "WASHABLE", WASH: "WASHABLE", F5: "F5",
    G4: "G4", "180": "180", GREY: "GREY", GRAY: "GREY", BLACK: "BLACK" };
  var WIRE_ALIASES = { LARGEWIRE: "LARGE_WIRE", LARGE: "LARGE_WIRE",
    SMALLWIRE: "SMALL_WIRE", SMALL: "SMALL_WIRE" };

  function MaterialError(msg) { this.name = "MaterialError"; this.message = msg; }
  MaterialError.prototype = Object.create(Error.prototype);

  function key(text) {
    if (typeof text === "boolean") { return ""; }
    if (typeof text === "number") {
      if (!isFinite(text) || Math.floor(text) !== text) { return ""; }
      text = String(text);
    }
    return String(text === null || text === undefined ? "" : text)
      .toUpperCase().replace(/[^A-Z0-9]/g, "");
  }
  function normaliseMediaCode(t) {
    var c = MEDIA_ALIASES[key(t)];
    if (!c) {
      throw new MaterialError("There is no weight on file for media " +
        JSON.stringify(t) + ". The media with weights are: " +
        MEDIA_CODES.join(", ") + ".");
    }
    return c;
  }
  function normaliseWireCode(t) {
    var c = WIRE_ALIASES[key(t)];
    if (!c) {
      throw new MaterialError("There is no wire called " + JSON.stringify(t) +
        ". The wire codes are " + WIRE_CODES.join(", ") + ".");
    }
    return c;
  }
  function materialDefaults() {
    return { version: DEFAULTS_VERSION, wire: clone(DEFAULT_WIRE),
             media: clone(DEFAULT_MEDIA) };
  }
  function mergedMaterials(stored) {
    var out = materialDefaults();
    if (!stored) { return out; }
    ["wire", "media"].forEach(function (kind) {
      var rows = stored[kind] || {};
      Object.keys(rows).forEach(function (written) {
        var code;
        try {
          code = kind === "wire" ? normaliseWireCode(written) : normaliseMediaCode(written);
        } catch (e) { return; }
        var row = rows[written] || {};
        Object.keys(row).forEach(function (f) {
          if (f in out[kind][code] || ["derived_from", "measured_at",
              "measured_by", "note"].indexOf(f) !== -1) {
            out[kind][code][f] = row[f];
          }
        });
      });
    });
    if (stored.version) { out.version = String(stored.version); }
    return out;
  }
  function needPositive(v, label) {
    var n = finite(v);
    if (n === null) { throw new MaterialError(label + " is not a number."); }
    if (!(n > 0)) { throw new MaterialError(label + " has to be more than zero."); }
    return n;
  }
  function wireMaterial(code, mats) {
    code = normaliseWireCode(code);
    var s = mats || materialDefaults(), row = s.wire[code];
    var w = needPositive(row.roll_width_mm, code + " roll width");
    var l = needPositive(row.roll_length_mm, code + " roll length");
    var kg = needPositive(row.roll_weight_kg, code + " roll weight");
    var area = w * l / 1e6;
    return { code: code, kg_per_m2: kg / area, roll_area_m2: area,
             roll_width_mm: w, roll_length_mm: l, roll_weight_kg: kg,
             basis: row.basis || "supplied_roll_mass",
             source: { mesh_opening_mm: row.mesh_opening_mm,
                       wire_diameter_mm: row.wire_diameter_mm,
                       roll_width_mm: w, roll_length_mm: l, roll_weight_kg: kg },
             settings_version: s.version || DEFAULTS_VERSION };
  }
  function mediaMaterial(code, mats) {
    code = normaliseMediaCode(code);
    var s = mats || materialDefaults(), row = s.media[code];
    var area = needPositive(row.stock_area_m2, code + " stock area");
    var basis = row.basis || "supplied_stock_mass";
    var rate, weight, source;
    if (basis.indexOf("derived_from_") === 0 && row.derived_from) {
      var parent = mediaMaterial(row.derived_from, s);
      rate = parent.kg_per_m2;
      weight = area * rate;
      source = { derived_from: parent.code, parent_rate_kg_per_m2: rate,
                 parent_source: parent.source, stock_area_m2: area,
                 stock_weight_kg_derived: weight };
    } else {
      weight = needPositive(row.stock_weight_kg, code + " stock weight");
      rate = weight / area;
      source = { stock_weight_kg: weight, stock_area_m2: area };
    }
    return { code: code, kg_per_m2: rate, stock_weight_kg: weight,
             stock_area_m2: area, basis: basis, source: source,
             roll_width_mm: row.roll_width_mm === undefined ? null : row.roll_width_mm,
             roll_length_mm: row.roll_length_mm === undefined ? null : row.roll_length_mm,
             settings_version: s.version || DEFAULTS_VERSION };
  }

  var WIRE_RULE_VERSION = "TAF-WIRE-SELECT-2026-10";
  var V_FORM_WIRE_BANDS = [[30, 60, "SMALL_WIRE"], [65, 110, "LARGE_WIRE"],
                           [115, Infinity, "SMALL_WIRE"]];
  function selectWire(construction, depth, override, rules) {
    var out = { code: null, overridden: false, status: "ok", reason: "",
                rule_version: WIRE_RULE_VERSION };
    if (override !== null && override !== undefined && override !== "") {
      out.code = normaliseWireCode(override);
      out.overridden = true;
      out.reason = "chosen on the order";
      return out;
    }
    if (construction === "V-form") {
      var d = finite(depth);
      if (d === null || !(d > 0)) {
        out.status = "invalid_input"; out.reason = "the nominal depth is missing";
        return out;
      }
      for (var i = 0; i < V_FORM_WIRE_BANDS.length; i++) {
        var b = V_FORM_WIRE_BANDS[i];
        if (b[0] <= d && d <= b[1]) {
          out.code = b[2];
          out.reason = "V-form at " + d + "mm deep takes " + b[2];
          return out;
        }
      }
      var best = null, bestOff = null;
      for (var j = 0; j < V_FORM_WIRE_BANDS.length; j++) {
        var c = V_FORM_WIRE_BANDS[j];
        var off = d < c[0] ? c[0] - d : d - c[1];
        if (bestOff === null || off < bestOff) { best = c; bestOff = off; }
      }
      out.code = best[2];
      out.reason = "V-form at " + d + "mm deep takes " + best[2] + ", from the nearest depth rule";
      return out;
    }
    var configured = (rules || {})[construction];
    if (configured) {
      out.code = normaliseWireCode(configured);
      out.reason = construction + " is set to " + configured;
      return out;
    }
    out.status = "needs_wire_rule";
    out.reason = "no wire has been set for " + (construction || "this filter");
    return out;
  }

  /* ── Settings ─────────────────────────────────────────────────────── */

  var BASE_ADDRESS_DEFAULT = "Unit 1/19 Tradelink Road, Hillcrest Queensland 4118 Australia";
  var COMPANY = { name: "Total Air Filtration", abn: "45 667 800 893",
                  phone: "07 3800 3448" };
  var MAX_BUNDLE_KG = 10.0;
  var DEFAULT_REQUIRED_COMPONENTS = {
    "Flat Panel":     ["wire", "media"],
    "Header":         ["wire", "media"],
    "V-form":         ["wire", "media"],
    "Flyscreen":      ["media"],
    "Stepped Filter": ["wire", "media"]
  };
  var DEFAULT_COUNTED_IF_KNOWN = {
    "Flat Panel":     ["filter_frame", "braces"],
    "Header":         ["filter_frame", "braces"],
    "V-form":         ["filter_frame", "braces"],
    "Flyscreen":      ["flyscreen_frame", "braces"],
    "Stepped Filter": ["filter_frame", "flyscreen_part"]
  };
  var DEFAULT_PACKAGING = { confirmed: true, base_kg: 0,
    basis: "default - wrapping counted as 0 kg until it is weighed" };
  var DEFAULT_MAX_PER_WRAP = 5;
  var DEFAULT_HANDLING_PROFILES = [{
    id: "HANDLING-412x412x90", version: 1, verified: true,
    match: { width_mm: 412, height_mm: 412, depth_mm: 90 }, max_per_wrap: 5,
    source: "supplied: 412 x 412 x 90 filters are wrapped five at most"
  }];
  var DEFAULT_WIRE_RULES = { "Flat Panel": "LARGE_WIRE", "Header": "LARGE_WIRE" };
  var SECTIONS = ["materials", "steel", "cut_profiles", "component_profiles",
    "brace_profiles", "mounting_frame_profiles", "wire_rules",
    "required_components", "packaging", "handling_profiles", "max_bundle_kg",
    "shipping_rounding", "company", "c_channel"];

  function settingsDefaults() {
    return {
      materials: materialDefaults(),
      steel: { density_kg_m3: null, basis: null,
               material: "galvanised steel stock", version: null },
      cut_profiles: [], component_profiles: [], brace_profiles: {},
      mounting_frame_profiles: [], wire_rules: clone(DEFAULT_WIRE_RULES),
      required_components: clone(DEFAULT_REQUIRED_COMPONENTS),
      counted_if_known: clone(DEFAULT_COUNTED_IF_KNOWN),
      packaging: clone(DEFAULT_PACKAGING),
      default_max_per_wrap: DEFAULT_MAX_PER_WRAP,
      handling_profiles: clone(DEFAULT_HANDLING_PROFILES),
      max_bundle_kg: MAX_BUNDLE_KG, shipping_rounding: "up_0.1",
      c_channel: cChannelDefaults(),
      company: { base_address: BASE_ADDRESS_DEFAULT }, versions: {}
    };
  }
  /* rows: [{key, value, version}] as calc_settings comes back from the
     database, or {key: {value, version}}. */
  function mergeSettings(rows) {
    var out = settingsDefaults();
    var map = {};
    if (Array.isArray(rows)) {
      rows.forEach(function (r) { map[r.key] = { value: r.value, version: r.version }; });
    } else { map = rows || {}; }
    Object.keys(map).forEach(function (section) {
      var row = map[section];
      if (SECTIONS.indexOf(section) === -1 || !row || row.value === null ||
          row.value === undefined) { return; }
      var v = row.value;
      if (section === "materials") { out.materials = mergedMaterials(v); }
      else if (section === "company") {
        Object.keys(v || {}).forEach(function (k) {
          if (typeof v[k] === "string") { out.company[k] = v[k]; }
        });
      } else if (section === "c_channel") {
        out.c_channel = cChannelMerged(v);
      } else if (section === "max_bundle_kg") {
        var n = Number(v);
        if (isFinite(n) && n > 0) { out.max_bundle_kg = n; }
      } else { out[section] = v; }
      out.versions[section] = row.version;
    });
    return out;
  }
  function baseAddress(s) {
    var t = String(((s || {}).company || {}).base_address || "").trim();
    return t || BASE_ADDRESS_DEFAULT;
  }
  function provenance(s, sections) {
    var v = (s && s.versions) || {}, out = {};
    sections.forEach(function (k) { out[k] = v[k] === undefined ? "default" : v[k]; });
    return out;
  }

  /* ── Bracing ──────────────────────────────────────────────────────── */

  var BRACE_RULE_VERSION = "TAF-BRACING-2026-10";
  var CROSS = "Cross Format";
  var BRACED_AS = { "Flat Panel": "Flat Panel", "Header": "Flat Panel",
                    "V-form": "V-form", "Flyscreen": "Flyscreen" };

  function bracing(construction, width, height, profile) {
    var out = { status: "ok", required: false, advisory: false, count: null,
                arrangement: null, message: "", reason: "",
                rule_version: BRACE_RULE_VERSION,
                construction: construction || "",
                long_side_mm: null, short_side_mm: null };
    var w = positive(width), h = positive(height);
    if (w === null || h === null) {
      out.status = "invalid_input";
      out.message = "Bracing not checked - the size is missing";
      out.reason = "width and height must both be more than zero";
      return out;
    }
    var L = Math.max(w, h), S = Math.min(w, h);
    out.long_side_mm = L; out.short_side_mm = S;
    var rule = BRACED_AS[construction || ""];
    if (!rule) {
      out.status = "needs_rule";
      out.message = "Bracing not checked - no rule for this filter";
      out.reason = "no bracing rule has been set for " +
        (construction || "an unknown filter type");
      return out;
    }
    if (rule === "Flat Panel") {
      if (L > 1300) { out.required = true; out.count = 2;
        out.reason = "long side " + L + "mm is over 1300mm"; }
      else if (S > 700) { out.required = true; out.count = 1;
        out.reason = "both sides are over 700mm"; }
    } else if (rule === "V-form") {
      if (L > 1300 && S > 700) { out.required = true;
        out.reason = "long side over 1300mm and short side over 700mm"; }
    } else {
      var narrow = S <= 150, wide = S > 650;
      if (narrow || wide) {
        out.required = true; out.message = "use brace in filter";
        out.reason = "short side " + S + "mm is " +
          (narrow ? "150mm or less" : "over 650mm");
      }
      if (L > 1300) {
        out.advisory = true;
        if (!out.required) { out.message = "consider bracing";
          out.reason = "long side " + L + "mm is over 1300mm"; }
      }
    }
    if (out.required && profile) {
      if (out.count === null && profile.count) {
        var c = parseInt(profile.count, 10);
        if (isFinite(c)) { out.count = c; }
      }
      if (profile.arrangement && out.count !== 2) { out.arrangement = String(profile.arrangement); }
    }
    if (out.count === 2) { out.arrangement = CROSS; }
    if (!out.required && !out.advisory) { out.message = "No brace required"; }
    if (out.required && !out.message) {
      out.message = out.count === 2 ? "Brace Required - 2 braces, Cross Format"
        : out.count === 1 ? "Brace Required - 1 brace" : "Brace Required";
    }
    return out;
  }
  function braceShortLabel(r) {
    if (r.status !== "ok") { return "CHECK"; }
    if (r.required) { return "YES" + (r.count ? " x" + r.count : ""); }
    if (r.advisory) { return "CONSIDER"; }
    return "NO";
  }

  /* ── Mounting frames ──────────────────────────────────────────────── */

  var MF_THICKNESS = 2.0;
  var MF_RULE_VERSION = "TAF-MOUNTING-FRAME-2026-10";

  function mfLength(spec, w, h) {
    if (spec && typeof spec === "object") {
      var base = { width: w, height: h, short: Math.min(w, h),
                   long: Math.max(w, h) }[String(spec.from || "")];
      if (base === undefined) { return null; }
      var mult = finite(spec.multiply === undefined ? 1 : spec.multiply) || 0;
      var add = finite(spec.add === undefined ? 0 : spec.add) || 0;
      return base * mult + add;
    }
    return finite(spec);
  }
  function mountingFrameProfile(w, h, profiles) {
    var k0 = Math.min(w, h), k1 = Math.max(w, h), rule = null;
    var list = profiles || [];
    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      if (!p.verified) { continue; }
      var sizes = p.sizes || [];
      for (var j = 0; j < sizes.length; j++) {
        var z = sizes[j];
        if (Math.min(z[0], z[1]) === k0 && Math.max(z[0], z[1]) === k1) { return p; }
      }
      if (p.custom_sizes && rule === null) { rule = p; }
    }
    return rule;
  }
  function mountingFrame(width, height, quantity, profile, steel) {
    var out = { status: "complete", errors: [], missing: [],
      thickness_mm: MF_THICKNESS, rule_version: MF_RULE_VERSION,
      width_mm: null, height_mm: null, quantity: null, profile_id: null,
      profile_version: null, steel: null, pieces: [], hardware: [],
      mounting_frame_weight_kg_each: null, mounting_frame_weight_kg_order: null,
      basis: null };
    var w = positive(width), h = positive(height);
    if (w === null || h === null) { out.errors.push("width and height must both be more than zero"); }
    var q = positiveInt(quantity === null || quantity === undefined ? 1 : quantity);
    if (q === null) { out.errors.push("quantity must be a whole number of 1 or more"); }
    out.width_mm = w; out.height_mm = h; out.quantity = q;
    if (out.errors.length) { out.status = "invalid_input"; return out; }
    var st = steel || {};
    var density = finite(st.density_kg_m3);
    out.steel = { density_kg_m3: density && density > 0 ? density : null,
                  basis: st.basis === undefined ? null : st.basis,
                  version: st.version === undefined ? null : st.version,
                  material: st.material || "galvanised steel stock" };
    if (!density || density <= 0) { out.missing.push("steel density (kg/m3) for the steel stock"); }
    if (!profile) {
      out.missing.push("a verified mounting-frame profile for " + w + " x " + h +
        " (strip width before folding, side lengths, corners, holes, hardware)");
    }
    if (out.missing.length) { out.status = "needs_mounting_frame_profile"; return out; }
    out.profile_id = profile.id === undefined ? null : profile.id;
    out.profile_version = profile.version === undefined ? null : profile.version;
    out.basis = profile.basis || "verified_profile";
    var t = finite(profile.thickness_mm) || MF_THICKNESS;
    if (Math.abs(t - MF_THICKNESS) > 1e-9) {
      out.errors.push("profile " + profile.id + " is " + t + "mm; mounting frames are 2mm");
      out.status = "invalid_input"; return out;
    }
    var steelEach = 0;
    (profile.pieces || []).forEach(function (pc) {
      var name = String(pc.name || "piece");
      var count = parseInt(pc.qty === undefined ? 1 : pc.qty, 10);
      var len = mfLength(pc.retained_length_mm, w, h);
      var dev = finite(pc.developed_flat_width_mm), sec = finite(pc.cross_section_area_mm2);
      if (!(count >= 1) || len === null || len <= 0 ||
          ((dev === null || dev <= 0) && (sec === null || sec <= 0))) {
        out.missing.push(name + ": length, quantity and either strip width or cross-section");
        return;
      }
      var kg, area, how;
      if (dev && dev > 0) { area = dev * len; kg = area * t * density / 1e9; how = "developed_flat_width"; }
      else { area = null; kg = sec * len * density / 1e9; how = "cross_section"; }
      out.pieces.push({ name: name, qty: count, retained_length_mm: len,
        developed_flat_width_mm: dev, cross_section_area_mm2: sec,
        retained_flat_area_mm2: area, kg_each_piece: kg, kg_per_frame: kg * count,
        method: how });
      steelEach += kg * count;
    });
    var removed = finite(profile.removed_area_mm2) || 0;
    var overlap = finite(profile.retained_overlap_area_mm2) || 0;
    steelEach += (overlap - removed) * t * density / 1e9;
    var hw = 0;
    (profile.hardware || []).forEach(function (it) {
      var kg = finite(it.kg_each), count = parseInt(it.qty === undefined ? 1 : it.qty, 10);
      if (kg === null || kg < 0 || !(count >= 0)) { out.missing.push("hardware " + it.name + ": weight"); return; }
      out.hardware.push({ name: it.name, qty: count, kg_each: kg, kg_per_frame: kg * count });
      hw += kg * count;
    });
    if (!out.pieces.length) { out.missing.push("the profile lists no steel pieces"); }
    if (out.missing.length) { out.status = "needs_mounting_frame_profile"; return out; }
    out.mounting_frame_weight_kg_each = steelEach + hw;
    out.mounting_frame_weight_kg_order = (steelEach + hw) * q;
    return out;
  }

  /* ── Filter types ─────────────────────────────────────────────────── */

  var CONSTRUCTIONS = ["Flat Panel", "V-form", "Flyscreen", "Stepped Filter", "Header"];
  // part_numbers.FILTER_TYPE_WORDINGS, kept identical by the parity test.
  var FILTER_TYPE_WORDINGS = {"vform": "V-form", "vfilter": "V-form", "vfilters": "V-form", "veeform": "V-form", "veefilter": "V-form", "vbank": "V-form", "veebank": "V-form", "vtype": "V-form", "vpleat": "V-form", "vpanel": "V-form", "vcell": "V-form", "pleatedpanel": "V-form", "pleatedpanelfilter": "V-form", "pleatedfilter": "V-form", "pleated": "V-form", "pleat": "V-form", "ppf": "V-form", "pleatpack": "V-form", "flatpanel": "Flat Panel", "flatpanelfilter": "Flat Panel", "panel": "Flat Panel", "panelfilter": "Flat Panel", "flatfilter": "Flat Panel", "flat": "Flat Panel", "fpf": "Flat Panel", "filterpad": "Flat Panel", "pad": "Flat Panel", "padfilter": "Flat Panel", "washablepanel": "Flat Panel", "stepped": "Stepped Filter", "steppedfilter": "Stepped Filter", "stepfilter": "Stepped Filter", "step": "Stepped Filter", "stppf": "Stepped Filter", "stppfw50": "Stepped Filter", "flyscreen": "Flyscreen", "flyscreens": "Flyscreen", "flyscren": "Flyscreen", "insectscreen": "Flyscreen", "meshscreen": "Flyscreen", "screen": "Flyscreen", "emesh": "Flyscreen", "expandedmesh": "Flyscreen", "header": "Header", "headerpanel": "Header"};

  function constructionOf(text) {
    var w = String(text === null || text === undefined ? "" : text).trim();
    if (!w) { return ""; }
    for (var i = 0; i < CONSTRUCTIONS.length; i++) {
      if (w.toLowerCase() === CONSTRUCTIONS[i].toLowerCase()) { return CONSTRUCTIONS[i]; }
    }
    var hit = FILTER_TYPE_WORDINGS[w.toLowerCase().replace(/[^a-z0-9]/g, "")];
    return hit && CONSTRUCTIONS.indexOf(hit) !== -1 ? hit : "";
  }

  /* ── Profiles ─────────────────────────────────────────────────────── */

  var CALC_VERSION = "TAF-FILTER-CALC-2026-10";
  var WS_SOURCE = "TAF production worksheet (pdf_generator._wire_media)";
  function wsV(pid, low, high, shortAdd, mult) {
    return [
      { id: pid, version: 1, kind: "wire", verified: true,
        constructions: ["V-form"], depth_min_mm: low, depth_max_mm: high,
        basis: "taf_worksheet_formula", source: WS_SOURCE, method: "linear",
        across_pleats: "long", width: { from: "short", add: shortAdd },
        length: { from: "long", multiply: mult, round: "nearest" },
        pieces_per_filter: 2, rotation_allowed: true, installed: "full_blank" },
      { id: pid + "-MEDIA", version: 1, kind: "media", verified: true,
        constructions: ["V-form"], depth_min_mm: low, depth_max_mm: high,
        basis: "taf_worksheet_formula", source: WS_SOURCE,
        method: "from_wire_blank", wire_profile: pid, width_add: 60,
        length_add: 40, pieces_per_filter: 1, installed: "full_blank" }
    ];
  }
  var BUILTIN_PROFILES = [
    { id: "TAF-WS-FLAT", version: 1, kind: "wire", verified: true,
      constructions: ["Flat Panel", "Header"], basis: "taf_worksheet_formula",
      source: WS_SOURCE, method: "linear", width: { from: "short", add: -10 },
      length: { from: "long", add: -10 }, pieces_per_filter: 2,
      rotation_allowed: true, installed: "full_blank" },
    { id: "TAF-WS-FLAT-MEDIA", version: 1, kind: "media", verified: true,
      constructions: ["Flat Panel", "Header"], basis: "taf_worksheet_formula",
      source: WS_SOURCE, method: "linear", flat: true,
      width: { from: "short" }, length: { from: "long" },
      pieces_per_filter: 1, installed: "full_blank" }
  ].concat(wsV("TAF-WS-V30-60", 30, 60, -15, 1.36),
           wsV("TAF-WS-V65-80", 65, 80, -10, 1.55),
           wsV("TAF-WS-V85-100", 85, 100, -10, 1.785),
           [{ id: "TAF-WS-FLYSCREEN-MEDIA", version: 1, kind: "media",
              verified: true, constructions: ["Flyscreen"],
              basis: "taf_worksheet_formula",
              source: "TAF production worksheet (pdf_generator._draw_fs)",
              method: "linear", flat: true, width: { from: "short", add: 20 },
              length: { from: "long", add: 20 }, pieces_per_filter: 1,
              installed: "full_blank" }]);

  function allProfiles(s) { return (s.cut_profiles || []).concat(BUILTIN_PROFILES); }
  function findProfile(profiles, pid, version) {
    var best = null;
    for (var i = 0; i < profiles.length; i++) {
      var p = profiles[i];
      if (String(p.id) !== String(pid)) { continue; }
      if (version !== null && version !== undefined && version !== "") {
        if (String(p.version) === String(version)) { return p; }
        continue;
      }
      if (best === null || (positiveInt(p.version) || 0) > (positiveInt(best.version) || 0)) { best = p; }
    }
    return best;
  }
  function matchProfile(profiles, kind, construction, depth) {
    var nearest = null, gap = null;
    for (var i = 0; i < profiles.length; i++) {
      var p = profiles[i];
      if (p.kind !== kind || !p.verified) { continue; }
      if ((p.constructions || []).indexOf(construction) === -1) { continue; }
      var lo = finite(p.depth_min_mm), hi = finite(p.depth_max_mm);
      if (lo !== null || hi !== null) {
        if (depth === null || depth === undefined) { continue; }
        var off = 0;
        if (lo !== null && depth < lo) { off = lo - depth; }
        else if (hi !== null && depth > hi) { off = depth - hi; }
        if (off > 0) {
          if (gap === null || off < gap) { nearest = p; gap = off; }
          continue;
        }
      }
      return p;
    }
    return nearest;
  }
  function roundBy(v, how) {
    if (how === "nearest") { return pyRound(v); }
    if (how === "up") { return Math.ceil(round9(v)); }
    if (how === "down") { return Math.floor(round9(v)); }
    return v;
  }
  function dim(spec, dims) {
    if (spec && typeof spec === "object") {
      var base = dims[String(spec.from || "")];
      if (base === undefined || base === null) { return null; }
      var m = finite(spec.multiply === undefined ? 1 : spec.multiply);
      var a = finite(spec.add === undefined ? 0 : spec.add);
      if (m === null || a === null) { return null; }
      return roundBy(base * m + a, spec.round);
    }
    return finite(spec);
  }
  function sumAllowances(v) {
    if (v === null || v === undefined || v === "") { return 0; }
    if (Array.isArray(v)) {
      var t = 0;
      for (var i = 0; i < v.length; i++) { var n = finite(v[i]); if (n === null) { return null; } t += n; }
      return t;
    }
    return finite(v);
  }
  function applyIncrement(v, profile, which) {
    var inc = profile.cut_increment_mm;
    if (inc && typeof inc === "object") { inc = inc[which]; }
    var step = positive(inc);
    return step ? ceilTo(v, step) : v;
  }
  function developedTriangular(span, depth, n) {
    var pitch = span / n;
    return 2 * n * Math.sqrt(Math.pow(pitch / 2, 2) + depth * depth);
  }
  function developedSegments(segs) {
    var t = 0;
    for (var i = 0; i < (segs || []).length; i++) {
      var dx = finite(segs[i][0]), dz = finite(segs[i][1]);
      if (dx === null || dz === null) { return null; }
      t += Math.hypot(dx, dz);
    }
    return t;
  }
  function profileCut(profile, dims, wireCut) {
    var method = profile.method, missing = [], width = null, length = null;
    if (method === "linear") {
      width = dim(profile.width, dims); length = dim(profile.length, dims);
      if (width === null) { missing.push("cut width rule"); }
      if (length === null) { missing.push("cut length rule"); }
    } else if (method === "from_wire_blank") {
      if (!wireCut) { missing.push("the wire blank this media is cut from"); }
      else {
        width = wireCut[0] + (finite(profile.width_add) || 0);
        length = wireCut[1] + (finite(profile.length_add) || 0);
      }
    } else if (method === "triangular_v" || method === "segments") {
      var straight = dim(profile.straight_dimension_mm, dims), developed = null;
      if (straight === null) { missing.push("straight cage dimension"); }
      if (method === "triangular_v") {
        var n = positiveInt(profile.v_count);
        var span = dim(profile.usable_span_mm, dims);
        var depth = dim(profile.peak_to_trough_mm, dims);
        if (!n) { missing.push("number of Vs"); }
        if (span === null || span <= 0) { missing.push("usable span across the Vs"); }
        if (depth === null || depth <= 0) { missing.push("peak-to-trough depth"); }
        if (n && span && span > 0 && depth && depth > 0) { developed = developedTriangular(span, depth, n); }
      } else {
        developed = developedSegments(profile.segments);
        if (!developed) { missing.push("cross-section segments"); }
      }
      if (straight !== null && developed) {
        var lw = sumAllowances(profile.width_allowances_mm);
        var ll = sumAllowances(profile.length_allowances_mm);
        var bend = finite(profile.bend_correction_mm || 0);
        if (lw === null || ll === null || bend === null) { missing.push("allowances"); }
        else { width = straight + lw; length = developed + ll + bend; }
      }
    } else if (method === "flat") {
      var uw = dim(profile.usable_width_mm, dims), ul = dim(profile.usable_length_mm, dims);
      var aw = sumAllowances(profile.width_allowances_mm), al = sumAllowances(profile.length_allowances_mm);
      if (uw === null || ul === null) { missing.push("confirmed usable media width and length"); }
      else if (aw === null || al === null) { missing.push("allowances"); }
      else { width = uw + aw; length = ul + al; }
    } else {
      missing.push("a cut method (profile says " + JSON.stringify(method) + ")");
    }
    if (missing.length || width === null || length === null) { return [null, missing]; }
    if (width <= 0 || length <= 0) {
      return [null, ["a cut size above zero (the profile gives " + width + " x " + length + ")"]];
    }
    return [[applyIncrement(width, profile, "width"), applyIncrement(length, profile, "length")], []];
  }

  /* ── The calculation ──────────────────────────────────────────────── */

  function rollFit(w, l, rw, rl, rot) {
    if (!rw || !rl) { return "not_configured"; }
    if (w <= rw && l <= rl) { return "fits"; }
    if (rot && l <= rw && w <= rl) { return "fits_rotated"; }
    return "cut_does_not_fit_roll";
  }
  function piecesOf(pieces, rate, rw, rl, rotDefault, errors, label) {
    var out = [];
    (pieces || []).forEach(function (p, i) {
      var w = positive(p.cut_width_mm), l = positive(p.cut_length_mm);
      var n = positiveInt(p.pieces_per_filter);
      if (w === null || l === null) {
        errors.push(label + " piece " + (i + 1) + ": cut width and length must be more than zero");
        return;
      }
      if (n === null) {
        errors.push(label + " piece " + (i + 1) + ": pieces per filter must be a whole number of 1 or more");
        return;
      }
      var rot = p.rotation_allowed === null || p.rotation_allowed === undefined ? rotDefault : !!p.rotation_allowed;
      var area = w * l / 1e6, kg = rate === null ? null : area * rate;
      out.push({ cut_width_mm: w, cut_length_mm: l, pieces_per_filter: n,
        area_m2_per_piece: area, kg_per_piece: kg, area_m2_per_filter: area * n,
        kg_contribution_per_filter: kg === null ? null : kg * n,
        rotation_allowed: rot, roll_fit: rollFit(w, l, rw, rl, rot) });
    });
    return out;
  }
  function installedOf(rule, blank, rate, missing, label) {
    if (typeof rule === "string") { rule = { rule: rule }; }
    if (!rule || !rule.rule) {
      missing.push(label + ": whether the whole blank stays in the filter, or the area that is kept");
      return null;
    }
    if (rule.rule === "full_blank") { return blank; }
    if (rule.rule === "retained_area") {
      var a = positive(rule.retained_area_mm2_per_filter);
      if (a === null || rate === null) { missing.push(label + ": retained area per filter"); return null; }
      return a / 1e6 * rate;
    }
    missing.push(label + ": unknown retention rule " + JSON.stringify(rule.rule));
    return null;
  }

  function blankResult(req) {
    return { status: "incomplete", calc_version: CALC_VERSION, errors: [],
      missing: [], notes: [], construction: "",
      filter_type: req.filter_type === undefined ? null : req.filter_type,
      width_mm: null, height_mm: null, nominal_depth_mm: null,
      order_quantity: null, wire: null, media_components: [],
      cut_mesh_area_m2_per_filter: null, wire_blank_weight_kg_per_filter: null,
      wire_blank_weight_kg_order: null, installed_wire_weight_kg_per_filter: null,
      installed_wire_weight_kg_order: null, media_blank_weight_kg_per_filter: null,
      media_blank_weight_kg_order: null, installed_media_weight_kg_per_filter: null,
      installed_media_weight_kg_order: null,
      known_media_blank_subtotal_kg_per_filter: null,
      known_media_installed_subtotal_kg_per_filter: null, bracing: null,
      components: [], known_material_weight_kg_per_filter: null,
      known_material_weight_kg_order: null, included_components: [],
      excluded_components: [], complete_filter_weight_kg_per_filter: null,
      complete_filter_weight_kg_order: null, weight_complete: false,
      provenance: {} };
  }

  function calculate(req, settings) {
    req = req || {};
    var s = settings || settingsDefaults();
    var out = blankResult(req), errors = out.errors, missing = out.missing;
    var mats = s.materials || materialDefaults();
    var construction = constructionOf(req.filter_type);
    out.construction = construction;
    if (req.filter_type && !construction) {
      errors.push("filter type " + JSON.stringify(req.filter_type) + " is not one this calculator knows");
    }
    function reqDim(k, label) {
      if (!(k in req) || req[k] === null || req[k] === "") { return null; }
      var v = typeof req[k] === "boolean" ? null : positive(req[k]);
      if (v === null) { errors.push(label + " must be a number more than zero"); }
      return v;
    }
    var w = reqDim("width_mm", "width"), h = reqDim("height_mm", "height");
    var d = reqDim("nominal_depth_mm", "nominal depth");
    var qraw = req.order_quantity;
    var qty = positiveInt(qraw === null || qraw === undefined || qraw === "" ? 1 : qraw);
    if (qty === null) { errors.push("order quantity must be a whole number of 1 or more"); }
    out.width_mm = w; out.height_mm = h; out.nominal_depth_mm = d; out.order_quantity = qty;
    var dims = {};
    if (w !== null && h !== null) {
      dims = { width: w, height: h, short: Math.min(w, h), long: Math.max(w, h) };
    }
    if (d !== null) { dims.depth = d; }
    var hasDims = w !== null && h !== null;
    var parts = req.parts || ["wire", "media"];
    var pleat = !!req.pleat_insert, headerOnly = !!req.header_only;
    var profiles = allProfiles(s);
    var required = ((s.required_components || {})[construction] || []).slice();
    if (pleat) { required = required.filter(function (c) { return c !== "filter_frame"; }); }
    if (headerOnly) { required = required.filter(function (c) { return c !== "wire" && c !== "media"; }); }
    if (errors.length) { out.status = "invalid_input"; return out; }

    var wireCut = null;
    var wireNeeded = parts.indexOf("wire") !== -1 && (required.indexOf("wire") !== -1 ||
      (req.wire !== null && req.wire !== undefined) || req.wire_material_override);
    if (wireNeeded && !headerOnly) {
      wireCut = calcWire(req, out, s, mats, profiles, construction, dims, hasDims, d, qty);
    }
    if (wireCut === null && out.wire === null && hasDims && construction) {
      wireCut = wireGeometry(req.wire || {}, profiles, construction, dims, d);
    }
    if (parts.indexOf("media") !== -1 && !headerOnly) {
      var comps = req.media_components;
      if ((comps === null || comps === undefined) && req.media_code !== null &&
          req.media_code !== undefined && req.media_code !== "") {
        comps = [{ media_code: req.media_code }];
      }
      if ((comps === null || comps === undefined) && required.indexOf("media") !== -1) {
        missing.push("which media this filter is made of");
      }
      (comps || []).forEach(function (c) {
        out.media_components.push(calcMedia(c, s, mats, profiles, construction, dims, hasDims, d, qty, wireCut));
      });
      sumMedia(out, qty);
    }
    if (construction && hasDims) {
      out.bracing = bracing(construction, dims.width, dims.height,
                            (s.brace_profiles || {})[construction]);
    }
    components(req, out, s, construction, required, dims, hasDims, qty);
    if (out.errors.length) { out.status = "invalid_input"; }
    else if (out.weight_complete) { out.status = "complete"; }
    else if (out.known_material_weight_kg_per_filter !== null) { out.status = "partial"; }
    else { out.status = "incomplete"; }
    out.provenance = { calc_version: CALC_VERSION, materials_version: mats.version,
      bracing_rule: BRACE_RULE_VERSION, wire_rule: WIRE_RULE_VERSION,
      settings: provenance(s, ["materials", "cut_profiles", "component_profiles",
        "brace_profiles", "steel", "mounting_frame_profiles", "required_components"]) };
    return out;
  }

  function wireGeometry(wireIn, profiles, construction, dims, depth) {
    if (wireIn.pieces && wireIn.pieces.length) {
      var w = positive(wireIn.pieces[0].cut_width_mm), l = positive(wireIn.pieces[0].cut_length_mm);
      return w && l ? [w, l] : null;
    }
    var p;
    if (wireIn.profile_id) {
      p = findProfile(profiles, wireIn.profile_id, wireIn.profile_version);
      if (!p || !p.verified) { return null; }
    } else { p = matchProfile(profiles, "wire", construction, depth); }
    if (!p) { return null; }
    return profileCut(p, dims)[0];
  }

  function calcWire(req, out, s, mats, profiles, construction, dims, hasDims, depth, qty) {
    var wireIn = req.wire || {};
    var res = { status: "complete", code: null, overridden: false, selection: null,
      profile_id: null, profile_version: null, measured_cut_pieces: false,
      material: null, pieces: [], roll_fit_status: null, missing: [], basis: null };
    out.wire = res;
    var sel;
    try { sel = selectWire(construction, depth, req.wire_material_override, s.wire_rules); }
    catch (e) { out.errors.push(e.message); res.status = "invalid_input"; return null; }
    res.selection = sel; res.code = sel.code; res.overridden = sel.overridden;
    var material = null;
    if (sel.code) { material = wireMaterial(sel.code, mats); res.material = material; }
    else { res.missing.push(sel.reason); }
    var profile = null, piecesIn = wireIn.pieces;
    if (piecesIn && piecesIn.length) {
      res.measured_cut_pieces = true; res.basis = "measured_cut_pieces";
    } else {
      piecesIn = null;
      if (wireIn.profile_id) {
        profile = findProfile(profiles, wireIn.profile_id, wireIn.profile_version);
        if (!profile) {
          res.missing.push("wire profile " + wireIn.profile_id + " v" +
            (wireIn.profile_version || "latest") + " does not exist");
        } else if (!profile.verified) {
          res.missing.push("wire profile " + profile.id + " is not verified yet");
          profile = null;
        }
      } else if (construction) {
        profile = matchProfile(profiles, "wire", construction, depth);
        if (!profile) {
          res.missing.push("a verified wire cut profile for " + construction + " at " +
            (depth ? depth : "?") + "mm deep");
        }
      } else { res.missing.push("the filter type, to find its cut profile"); }
      if (profile) {
        if (!hasDims) { res.missing.push("the filter's width and height"); }
        else {
          var r = profileCut(profile, dims);
          r[1].forEach(function (m) { res.missing.push("wire profile " + profile.id + ": " + m); });
          if (r[0]) {
            res.profile_id = profile.id;
            res.profile_version = profile.version === undefined ? null : profile.version;
            res.basis = profile.basis === undefined ? null : profile.basis;
            piecesIn = [{ cut_width_mm: r[0][0], cut_length_mm: r[0][1],
              pieces_per_filter: profile.pieces_per_filter === undefined ? 1 : profile.pieces_per_filter,
              rotation_allowed: profile.rotation_allowed }];
          }
        }
      }
    }
    if (!piecesIn) {
      res.status = "needs_cut_rule"; res.cut_width_mm = null; res.cut_length_mm = null;
      res.missing.forEach(function (m) { out.missing.push("wire: " + m); });
      return null;
    }
    var rw = material ? material.roll_width_mm : 1200, rl = material ? material.roll_length_mm : 30000;
    var rate = material ? material.kg_per_m2 : null;
    res.pieces = piecesOf(piecesIn, rate, rw, rl, true, out.errors, "wire");
    if (out.errors.length) { res.status = "invalid_input"; return null; }
    var fits = res.pieces.map(function (p) { return p.roll_fit; });
    res.roll_fit_status = fits.indexOf("cut_does_not_fit_roll") !== -1 ? "cut_does_not_fit_roll" : "fits";
    out.cut_mesh_area_m2_per_filter = sum(res.pieces.map(function (p) { return p.area_m2_per_filter; }));
    var cut = [res.pieces[0].cut_width_mm, res.pieces[0].cut_length_mm];
    if (res.roll_fit_status === "cut_does_not_fit_roll") {
      res.status = "cut_does_not_fit_roll";
      var msg = "wire: a blank is wider than the 1200mm roll every way it may be cut - it needs a verified multi-piece or spliced profile";
      res.missing.push(msg); out.missing.push(msg);
      return cut;
    }
    if (rate === null) {
      res.status = "needs_wire_rule";
      res.missing.forEach(function (m) { out.missing.push("wire: " + m); });
      return cut;
    }
    var blank = sum(res.pieces.map(function (p) { return p.kg_contribution_per_filter; }));
    out.wire_blank_weight_kg_per_filter = blank;
    out.wire_blank_weight_kg_order = blank * qty;
    var rule = wireIn.installed || (profile || {}).installed;
    var miss = [];
    var inst = installedOf(rule, blank, rate, miss, "wire");
    miss.forEach(function (m) { res.missing.push(m); out.missing.push(m); });
    if (inst === null) { res.status = "blank_only"; }
    else {
      out.installed_wire_weight_kg_per_filter = inst;
      out.installed_wire_weight_kg_order = inst * qty;
    }
    return cut;
  }

  function calcMedia(comp, s, mats, profiles, construction, dims, hasDims, depth, qty, wireCut) {
    var res = { status: "complete", media_code: null, material: null,
      rate_kg_per_m2: null, basis: null, profile_id: null, profile_version: null,
      measured_cut_pieces: false, pieces: [], cut_area_m2_per_filter: null,
      blank_weight_kg_per_filter: null, blank_weight_kg_order: null,
      installed_weight_kg_per_filter: null, installed_weight_kg_order: null,
      media_roll_fit_status: null, missing: [], errors: [] };
    var code;
    try { code = normaliseMediaCode(comp.media_code); }
    catch (e) {
      res.status = "unsupported_media_code"; res.errors.push(e.message);
      res.media_code = comp.media_code === undefined ? null : comp.media_code;
      return res;
    }
    var material = mediaMaterial(code, mats);
    res.media_code = code; res.material = material;
    res.rate_kg_per_m2 = material.kg_per_m2; res.basis = material.basis;
    var piecesIn = comp.pieces, profile = null;
    if (piecesIn && piecesIn.length) { res.measured_cut_pieces = true; }
    else {
      piecesIn = null;
      if (comp.profile_id) {
        profile = findProfile(profiles, comp.profile_id, comp.profile_version);
        if (!profile || !profile.verified) {
          res.missing.push("media profile " + comp.profile_id + " is missing or not verified");
          profile = null;
        }
      } else if (construction) {
        profile = matchProfile(profiles, "media", construction, depth);
        if (!profile) {
          res.missing.push("a verified media cut profile for " + construction +
            (depth ? " at " + depth + "mm deep" : ""));
        }
      } else { res.missing.push("the filter type, to find its cut profile"); }
      if (profile) {
        if (!hasDims) { res.missing.push("the filter's width and height"); }
        else {
          var r = profileCut(profile, dims, wireCut);
          r[1].forEach(function (m) { res.missing.push("media profile " + profile.id + ": " + m); });
          if (r[0]) {
            res.profile_id = profile.id;
            res.profile_version = profile.version === undefined ? null : profile.version;
            piecesIn = [{ cut_width_mm: r[0][0], cut_length_mm: r[0][1],
              pieces_per_filter: profile.pieces_per_filter === undefined ? 1 : profile.pieces_per_filter,
              rotation_allowed: profile.rotation_allowed }];
          }
        }
      }
    }
    if (!piecesIn) { res.status = "needs_media_cut_rule"; return res; }
    res.pieces = piecesOf(piecesIn, material.kg_per_m2, positive(material.roll_width_mm),
      positive(material.roll_length_mm), false, res.errors, "media " + code);
    if (res.errors.length) { res.status = "invalid_input"; return res; }
    var fits = res.pieces.map(function (p) { return p.roll_fit; });
    res.media_roll_fit_status = fits.indexOf("not_configured") !== -1 ? "not_configured"
      : fits.indexOf("cut_does_not_fit_roll") !== -1 ? "cut_does_not_fit_roll" : "fits";
    res.cut_area_m2_per_filter = sum(res.pieces.map(function (p) { return p.area_m2_per_filter; }));
    if (res.media_roll_fit_status === "cut_does_not_fit_roll") {
      res.status = "cut_does_not_fit_roll";
      res.missing.push("media " + code + ": a piece does not fit the roll");
      return res;
    }
    var blank = sum(res.pieces.map(function (p) { return p.kg_contribution_per_filter; }));
    res.blank_weight_kg_per_filter = blank;
    res.blank_weight_kg_order = blank * qty;
    var rule = comp.installed || (profile || {}).installed;
    var inst = installedOf(rule, blank, material.kg_per_m2, res.missing, "media " + code);
    if (inst === null) { res.status = "blank_only"; }
    else { res.installed_weight_kg_per_filter = inst; res.installed_weight_kg_order = inst * qty; }
    return res;
  }

  function sumMedia(out, qty) {
    var comps = out.media_components;
    if (!comps.length) { return; }
    comps.forEach(function (c) {
      c.missing.forEach(function (m) { out.missing.push("media: " + m); });
      if (c.status === "invalid_input" || c.status === "unsupported_media_code") {
        c.errors.forEach(function (e) { out.errors.push("media: " + e); });
      }
    });
    var blanks = comps.map(function (c) { return c.blank_weight_kg_per_filter; });
    var kb = blanks.filter(function (b) { return b !== null; });
    if (kb.length) { out.known_media_blank_subtotal_kg_per_filter = sum(kb); }
    if (kb.length && kb.length === blanks.length) {
      out.media_blank_weight_kg_per_filter = sum(kb);
      out.media_blank_weight_kg_order = sum(kb) * qty;
    }
    var inst = comps.map(function (c) { return c.installed_weight_kg_per_filter; });
    var ki = inst.filter(function (b) { return b !== null; });
    if (ki.length) { out.known_media_installed_subtotal_kg_per_filter = sum(ki); }
    if (ki.length && ki.length === inst.length) {
      out.installed_media_weight_kg_per_filter = sum(ki);
      out.installed_media_weight_kg_order = sum(ki) * qty;
    }
  }

  function channelLengthMm(dims, profile) {
    var p = profile || {};
    var allow = finite(p.side_allowance_mm); if (allow === null) { allow = 2; }
    var lip = finite(p.lip_mm); if (lip === null) { lip = 20; }
    var lips = positiveInt(p.lips) || 2;
    return 2 * (dims.width - allow) + 2 * (dims.height - allow) + lips * lip;
  }
  function depthKey(depth) {
    var d = finite(depth);
    return d === null ? "" : String(d);
  }
  function channelKg(p, dims) {
    var rates = p.kg_per_m_by_depth || {};
    var rate = positive(rates[depthKey(dims.depth)]);
    if (rate === null) { return null; }
    return rate * channelLengthMm(dims, p) / 1000;
  }
  var FRAMED_IN_CHANNEL = ["Flat Panel", "Header", "V-form"];
  function cChannelFrame(req, construction, dims, hasDims, s) {
    if (FRAMED_IN_CHANNEL.indexOf(construction) === -1 || req.pleat_insert || !hasDims ||
        dims.depth === undefined || dims.depth === null) { return [null, {}]; }
    var method = String(req.frame_method || "u");
    var cut = frameCutList(dims.width, dims.height, method, dims.depth);
    var r = calculateCChannelFrameWeight(cut, 1, s);
    return [r.frame_weight_kg, { basis: "c_channel", frame_method: method,
      sections: r.sections, c_channel_version: r.settings_version,
      warnings: r.calculation_warnings }];
  }
  function frameMissing(name, dims) {
    if (name === "filter_frame" && dims.depth !== undefined && dims.depth !== null) {
      return "filter frame: kg per metre of " + depthKey(dims.depth) + "mm channel";
    }
    if (name === "flyscreen_frame") { return "flyscreen frame: kg per metre of flyscreen frame"; }
    return name.replace(/_/g, " ") + ": a verified weight profile";
  }

  function profileComponent(name, construction, profiles, dims, hasDims) {
    var list = profiles || [];
    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      if (p.name !== name || !p.verified) { continue; }
      if ((p.constructions || [construction]).indexOf(construction) === -1) { continue; }
      var kg = null;
      if (p.method === "measured_each") { kg = positive(p.kg_each); }
      else if (p.method === "channel_per_m" && hasDims) { kg = channelKg(p, dims); }
      else if (p.method === "per_perimeter_m" && hasDims) {
        var r = positive(p.kg_per_m);
        kg = r === null ? null : r * 2 * (dims.width + dims.height) / 1000;
      } else if (p.method === "per_face_m2" && hasDims) {
        var r2 = positive(p.kg_per_m2);
        kg = r2 === null ? null : r2 * dims.width * dims.height / 1e6;
      }
      if (kg !== null) {
        return [kg, "known", { profile_id: p.id === undefined ? null : p.id,
          profile_version: p.version === undefined ? null : p.version,
          basis: p.basis === undefined ? null : p.basis }];
      }
    }
    return [null, "unknown", {}];
  }
  function comp(name, required, status, kg, extra) {
    var row = { name: name, required: required, status: status, installed_kg_per_filter: kg };
    Object.keys(extra || {}).forEach(function (k) { row[k] = extra[k]; });
    return row;
  }

  function components(req, out, s, construction, required, dims, hasDims, qty) {
    var comps = [], missing = out.missing;
    if (required.indexOf("wire") !== -1 || out.wire) {
      var kw = out.installed_wire_weight_kg_per_filter;
      comps.push(comp("wire", required.indexOf("wire") !== -1, kw !== null ? "known" : "unknown", kw));
    }
    if (required.indexOf("media") !== -1 || out.media_components.length) {
      var km = out.installed_media_weight_kg_per_filter;
      comps.push(comp("media", required.indexOf("media") !== -1, km !== null ? "known" : "unknown", km));
    }
    var optional = (((s.counted_if_known || {})[construction]) || []).filter(function (c) {
      return required.indexOf(c) === -1 && !(req.pleat_insert && c === "filter_frame");
    });
    ["filter_frame", "flyscreen_frame", "flyscreen_part"].forEach(function (name) {
      if (required.indexOf(name) === -1 && optional.indexOf(name) === -1) { return; }
      var r = profileComponent(name, construction, s.component_profiles, dims, hasDims);
      if (r[0] === null && name === "filter_frame") {
        var cf = cChannelFrame(req, construction, dims, hasDims, s);
        r = [cf[0], cf[0] !== null ? "known" : "unknown", cf[1]];
      }
      if (required.indexOf(name) !== -1) {
        if (r[0] === null) { missing.push(frameMissing(name, dims)); }
        comps.push(comp(name, true, r[1], r[0], r[2]));
      } else if (r[0] !== null) {
        comps.push(comp(name, false, r[1], r[0], r[2]));
      }
    });
    if (optional.indexOf("braces") !== -1) {
      var ob = out.bracing || {};
      var oprof = (s.brace_profiles || {})[construction] || {};
      var oeach = positive(oprof.kg_each_including_fixings), ocount = ob.count;
      if (ob.status === "ok" && ob.required && oeach !== null && ocount) {
        comps.push(comp("braces", false, "known", oeach * ocount, { count: ocount,
          kg_each: oeach, profile_version: oprof.version === undefined ? null : oprof.version }));
      }
    }
    if (required.indexOf("braces") !== -1) {
      var b = out.bracing;
      if (!b || b.status !== "ok") {
        comps.push(comp("braces", true, "unknown", null));
        missing.push("braces: bracing could not be checked");
      } else if (!b.required) {
        comps.push(comp("braces", true, "not_applicable", 0, { reason: "no brace required" }));
      } else {
        var prof = (s.brace_profiles || {})[construction] || {};
        var each = positive(prof.kg_each_including_fixings), count = b.count;
        if (each === null || !count) {
          var need = [];
          if (!count) { need.push("how many braces"); }
          if (each === null) { need.push("brace weight with its fixings"); }
          missing.push("braces: " + need.join(" and "));
          comps.push(comp("braces", true, "unknown", null, { count: count }));
        } else {
          comps.push(comp("braces", true, "known", each * count, { count: count,
            kg_each: each, profile_version: prof.version === undefined ? null : prof.version }));
        }
      }
    }
    if (req.includes_mounting_frame) {
      var mf = req.mounting_frame || {};
      var mw = mf.width_mm !== undefined ? mf.width_mm : dims.width;
      var mh = mf.height_mm !== undefined ? mf.height_mm : dims.height;
      var mp = mountingFrameProfile(positive(mw) || 0, positive(mh) || 0, s.mounting_frame_profiles);
      var r = mountingFrame(mw, mh, 1, mp, s.steel);
      var kg = r.mounting_frame_weight_kg_each;
      if (kg === null) { r.missing.forEach(function (m) { missing.push("mounting frame: " + m); }); }
      comps.push(comp("mounting_frame", true, kg !== null ? "known" : "unknown", kg, { detail: r }));
    }
    (req.components || []).forEach(function (x) {
      var name = String(x.name || "component");
      var reqd = x.required === undefined ? true : !!x.required;
      if (x.not_applicable) { comps.push(comp(name, reqd, "not_applicable", 0)); return; }
      var kg = finite(x.kg_per_filter);
      if (kg === null || kg < 0) {
        comps.push(comp(name, reqd, "unknown", null));
        if (reqd) { missing.push(name + ": its weight"); }
      } else { comps.push(comp(name, reqd, "known", kg, { basis: x.basis === undefined ? null : x.basis })); }
    });
    out.components = comps;
    var known = comps.filter(function (c) { return c.status === "known" || c.status === "not_applicable"; });
    var unknownReq = comps.filter(function (c) { return c.required && c.status === "unknown"; });
    out.included_components = known.map(function (c) { return c.name; });
    out.excluded_components = comps.filter(function (c) { return c.status === "unknown"; })
      .map(function (c) { return c.name; });
    if (known.length && known.some(function (c) { return c.status === "known"; })) {
      var t = sum(known.map(function (c) { return c.installed_kg_per_filter || 0; }));
      out.known_material_weight_kg_per_filter = t;
      out.known_material_weight_kg_order = t * qty;
    }
    var names = comps.map(function (c) { return c.name; });
    if (construction && comps.length && !unknownReq.length &&
        required.every(function (n) { return names.indexOf(n) !== -1; })) {
      var total = sum(known.map(function (c) { return c.installed_kg_per_filter || 0; }));
      out.complete_filter_weight_kg_per_filter = total;
      out.complete_filter_weight_kg_order = total * qty;
      out.weight_complete = true;
    }
  }

  function requestFromItem(item) {
    var saved = clone(item.Calculator || {}) || {};
    var req = { filter_type: item["Filter Type"], width_mm: item.Short,
      height_mm: item.Long, nominal_depth_mm: item.Channel,
      order_quantity: item.Quantity, pleat_insert: !!item["Pleat Insert"],
      header_only: !!item.Header };
    var media = String(item["Media Type"] || "").trim();
    if (media && !("media_components" in saved)) {
      var c = { media_code: media };
      if (saved.media_profile_id) { c.profile_id = saved.media_profile_id; }
      if (saved.media_profile_version) { c.profile_version = saved.media_profile_version; }
      req.media_components = [c];
    }
    ["wire", "wire_material_override", "media_components", "components",
     "includes_mounting_frame", "mounting_frame"].forEach(function (k) {
      if (k in saved) { req[k] = saved[k]; }
    });
    if (item["Frame Method"]) { req.frame_method = String(item["Frame Method"]); }
    return req;
  }

  /* ── Packing ──────────────────────────────────────────────────────── */

  var PACKING_RULE_VERSION = "TAF-PACKING-2026-10";
  var EPS = 1e-9;
  function PackingError(msg) { this.name = "PackingError"; this.message = msg; }
  PackingError.prototype = Object.create(Error.prototype);

  function split(quantity, capacity) {
    var q = positiveInt(quantity), c = positiveInt(capacity);
    if (q === null) { throw new PackingError("The quantity has to be a whole number of 1 or more."); }
    if (c === null) { throw new PackingError("Filters per wrap has to be a whole number of 1 or more."); }
    var out = [];
    for (var i = 0; i < Math.floor(q / c); i++) { out.push(c); }
    if (q % c) { out.push(q % c); }
    return out;
  }
  function checkQuantities(wq, quantity) {
    if (!Array.isArray(wq) || !wq.length) { throw new PackingError("Give at least one wrap."); }
    var out = wq.map(function (q, i) {
      var n = typeof q === "string" ? null : positiveInt(q);
      if (n === null) {
        throw new PackingError("Wrap " + (i + 1) + " has to hold a whole number of 1 or more filters (it says " + JSON.stringify(q) + ").");
      }
      return n;
    });
    var t = sum(out);
    if (t !== quantity) { throw new PackingError("The wraps hold " + t + " filters but the line is for " + quantity + "."); }
    return out;
  }
  function resolveQuantities(quantity, wq, max) {
    var q = positiveInt(quantity);
    if (q === null) { throw new PackingError("The quantity has to be a whole number of 1 or more."); }
    var hasW = wq !== null && wq !== undefined, hasM = max !== null && max !== undefined;
    if (hasW && hasM) { throw new PackingError("Give the wrap quantities or a maximum per wrap, not both."); }
    if (hasW) { return checkQuantities(wq, q); }
    if (hasM) {
      var cap = typeof max === "string" ? null : positiveInt(max);
      if (cap === null) { throw new PackingError("The maximum per wrap has to be a whole number of 1 or more."); }
      return split(q, cap);
    }
    return null;
  }
  function letters(n) {
    var out = "";
    while (n) { var r = (n - 1) % 26; out = String.fromCharCode(65 + r) + out; n = Math.floor((n - 1) / 26); }
    return out;
  }
  function wrapCodes(perLine) {
    var lines = perLine.length;
    if (lines === 1) {
      var n = perLine[0], one = [];
      for (var i = 1; i <= n; i++) { one.push(i + " of " + n); }
      return [one];
    }
    return perLine.map(function (n, li) {
      if (n === 1) { return [(li + 1) + "/" + lines]; }
      var codes = [];
      for (var j = 1; j <= n; j++) { codes.push((li + 1) + letters(j) + "/" + lines); }
      return codes;
    });
  }
  function packagingKg(spec, q) {
    if (typeof spec === "function") { return nonNegative(spec(q)); }
    if (!spec || typeof spec !== "object" || !spec.confirmed) { return null; }
    if (spec.by_quantity && typeof spec.by_quantity === "object") {
      var v = spec.by_quantity[String(q)];
      return nonNegative(v);
    }
    var base = nonNegative(spec.base_kg === undefined ? 0 : spec.base_kg);
    var per = nonNegative(spec.per_filter_kg === undefined ? 0 : spec.per_filter_kg);
    if (base === null || per === null) { return null; }
    return base + per * q;
  }
  function bundleKg(unit, q, packaging) {
    if (unit === null || unit === undefined) { return null; }
    var p = packagingKg(packaging, q);
    return p === null ? null : unit * q + p;
  }
  function weightCapacity(unit, packaging, upto, maxKg) {
    var max = maxKg === undefined ? MAX_BUNDLE_KG : maxKg;
    if (unit === null || unit === undefined || unit < 0) { return null; }
    if (packagingKg(packaging, 1) === null) { return null; }
    var fixed = packaging && typeof packaging === "object" && !packaging.by_quantity &&
      !nonNegative(packaging.per_filter_kg === undefined ? 0 : packaging.per_filter_kg);
    if (fixed && unit > 0) {
      var base = packagingKg(packaging, 0) || 0;
      var n = Math.floor((max - base) / unit + EPS);
      return Math.max(0, Math.min(n, upto));
    }
    var best = 0;
    for (var q = 1; q <= upto; q++) {
      var kg = bundleKg(unit, q, packaging);
      if (kg === null) { return null; }
      if (kg <= max + EPS) { best = q; }
    }
    return best;
  }
  function handlingLimit(w, h, d, construction, profiles) {
    w = positive(w); h = positive(h); d = positive(d);
    if (w === null || h === null) { return null; }
    var list = profiles || [];
    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      if (!p.verified) { continue; }
      var m = p.match || {}, mw = positive(m.width_mm), mh = positive(m.height_mm);
      if (mw === null || mh === null) { continue; }
      if (Math.min(mw, mh) !== Math.min(w, h) || Math.max(mw, mh) !== Math.max(w, h)) { continue; }
      var md = positive(m.depth_mm);
      if (md !== null && md !== d) { continue; }
      if (m.construction && m.construction !== construction) { continue; }
      if (positiveInt(p.max_per_wrap)) { return p; }
    }
    return null;
  }
  function wrapRows(qs, group, unit, packaging, maxKg) {
    return qs.map(function (q) {
      var raw = bundleKg(unit, q, packaging);
      return { quantity: q, group: group, packaging_kg: packagingKg(packaging, q),
               raw_kg: raw, over_limit: raw !== null && raw > maxKg + EPS };
    });
  }
  function checkGroups(groups, quantity) {
    if (!groups || !groups.length) { return [{ name: null, quantity: quantity }]; }
    var out = [], seen = {};
    groups.forEach(function (g, i) {
      var name = String((g || {}).name || "").trim(), n = positiveInt((g || {}).quantity);
      if (!name) { throw new PackingError("Area " + (i + 1) + " needs a name."); }
      if (seen[name.toLowerCase()]) { throw new PackingError("There are two areas called " + name + "."); }
      if (n === null) { throw new PackingError(name + " has to be a whole number of 1 or more filters."); }
      seen[name.toLowerCase()] = true;
      out.push({ name: name, quantity: n });
    });
    var t = sum(out.map(function (g) { return g.quantity; }));
    if (t !== quantity) { throw new PackingError("The areas add up to " + t + " filters but the line is for " + quantity + "."); }
    return out;
  }
  var FALLBACK_MAX_PER_WRAP = 5;
  function propose(quantity, unit, packaging, handlingMax, staffMax, groups, maxKg, fallbackMax) {
    var max = maxKg === undefined ? MAX_BUNDLE_KG : maxKg;
    var q = positiveInt(quantity);
    if (q === null) { throw new PackingError("The quantity has to be a whole number of 1 or more."); }
    var u = finite(unit);
    var limits = { max_kg: max, weight: weightCapacity(u, packaging, q, max),
                   handling: positiveInt(handlingMax), staff: positiveInt(staffMax) };
    var out = { rule_version: PACKING_RULE_VERSION, quantity: q, limits: limits,
                capacity: null, wraps: [], issues: [], status: "ok", compliant: false };
    var gl = checkGroups(groups, q);
    if (limits.weight === 0) {
      out.status = "single_item_exception"; out.capacity = 1;
      var one = bundleKg(u, 1, packaging);
      out.issues.push("One filter with its wrapping weighs " + one.toFixed(3) + " kg, over the " +
        max + " kg limit on its own. It cannot be split - decide how it is handled.");
      gl.forEach(function (g) {
        var ones = []; for (var i = 0; i < g.quantity; i++) { ones.push(1); }
        out.wraps = out.wraps.concat(wrapRows(ones, g.name, u, packaging, max));
      });
      return out;
    }
    var caps = [limits.weight, limits.handling, limits.staff].filter(function (c) { return c !== null; });
    var weightKnown = limits.weight !== null;
    if (!caps.length) {
      caps = [q === 1 ? 1 : (positiveInt(fallbackMax) || FALLBACK_MAX_PER_WRAP)];
    }
    var cap = Math.min.apply(null, caps);
    out.capacity = cap;
    gl.forEach(function (g) { out.wraps = out.wraps.concat(wrapRows(split(g.quantity, cap), g.name, u, packaging, max)); });
    if (!weightKnown) {
      out.status = "needs_weight_check";
      out.issues.push("The bundle weight is not known yet - weigh the wrapped bundles before calling this packing done.");
    }
    out.compliant = weightKnown && !out.wraps.some(function (w) { return w.over_limit; });
    return out;
  }
  function checkPlan(wraps, quantity, unit, packaging, handlingMax, staffMax, groups, maxKg) {
    var max = maxKg === undefined ? MAX_BUNDLE_KG : maxKg;
    var q = positiveInt(quantity);
    if (q === null) { throw new PackingError("The quantity has to be a whole number of 1 or more."); }
    var qs = checkQuantities(wraps.map(function (w) { return w.quantity; }), q);
    var gl = checkGroups(groups, q);
    if (groups && groups.length) {
      gl.forEach(function (g) {
        var held = sum(wraps.filter(function (w) { return w.group === g.name; }).map(function (w) { return w.quantity; }));
        if (held !== g.quantity) { throw new PackingError("The wraps for " + g.name + " hold " + held + " filters; it asked for " + g.quantity + "."); }
      });
      var names = gl.map(function (g) { return g.name; });
      if (wraps.some(function (w) { return names.indexOf(w.group) === -1; })) {
        throw new PackingError("Every wrap has to belong to one of the areas.");
      }
    }
    var u = finite(unit), hm = positiveInt(handlingMax), sm = positiveInt(staffMax);
    var issues = [], rows = [];
    wraps.forEach(function (w, i) {
      var n = qs[i], raw = bundleKg(u, n, packaging), measured = positive(w.measured_weight_kg);
      var over = (raw !== null && raw > max + EPS) || (measured !== null && measured > max + EPS);
      if (hm && n > hm) { issues.push("Wrap " + (i + 1) + " holds " + n + "; this size is handled " + hm + " at most."); }
      if (sm && n > sm) { issues.push("Wrap " + (i + 1) + " holds " + n + "; the limit set for this line is " + sm + "."); }
      if (raw !== null && raw > max + EPS) { issues.push("Wrap " + (i + 1) + " would weigh " + raw.toFixed(3) + " kg, over " + max + " kg."); }
      if (measured !== null && measured > max + EPS) { issues.push("Wrap " + (i + 1) + " was weighed at " + measured + " kg, over " + max + " kg - repack and reweigh it."); }
      rows.push({ quantity: n, group: w.group === undefined ? null : w.group, raw_kg: raw,
                  packaging_kg: packagingKg(packaging, n), over_limit: over });
    });
    var out = { ok: !issues.length, issues: issues, wraps: rows,
                weight_known: rows.every(function (r) { return r.raw_kg !== null; }), proposal: null };
    if (issues.length) {
      try { out.proposal = propose(q, u, packaging, hm, sm, groups, max); } catch (e) { out.proposal = null; }
    }
    return out;
  }
  function instruction(qs) {
    var order = [], counts = {};
    qs.forEach(function (q) { if (!(q in counts)) { order.push(q); counts[q] = 0; } counts[q]++; });
    var parts = order.map(function (q) { return "Wrap " + q + " Filter" + (q === 1 ? "" : "s") + " x " + counts[q]; });
    return parts.length ? "(" + parts.join(" + ") + ")" : "";
  }
  function planInstructions(plan) {
    var wraps = plan.wraps || [], groups = plan.groups || [];
    if (!groups.length) { return [instruction(wraps.map(function (w) { return w.quantity; }))]; }
    return groups.map(function (g) {
      var mine = wraps.filter(function (w) { return w.group === g.name; }).map(function (w) { return w.quantity; });
      return g.name + ": " + g.quantity + " filters " + instruction(mine);
    });
  }

  /* ── Weights on labels ────────────────────────────────────────────── */

  function roundPackage(raw, policy) {
    if (policy === "up_0.1") { return (Math.ceil(round9(raw * 10)) / 10).toFixed(1); }
    return raw.toFixed(3);
  }
  function resolveWrapWeight(wrap, unit, packaging, policy) {
    var q = positiveInt(wrap.quantity) || 0;
    var measured = positive(wrap.measured_weight_kg);
    if (measured !== null) {
      var text = String(wrap.measured_weight_text || "").trim() || String(measured);
      return { raw_kg: measured, display: trimZeros(text), source: "measured", missing: [] };
    }
    var missing = [];
    if (unit === null || unit === undefined) { missing.push("a complete filter weight"); }
    var pack;
    if (wrap.packaging_weight_kg !== null && wrap.packaging_weight_kg !== undefined && wrap.packaging_confirmed) {
      pack = wrap.packaging_weight_kg ? positive(wrap.packaging_weight_kg) : 0;
    } else { pack = packagingKg(packaging, q); }
    if (pack === null) { missing.push("the wrapping's weight"); }
    if (missing.length) { return { raw_kg: null, display: "", source: "unknown", missing: missing }; }
    var raw = unit * q + pack;
    return { raw_kg: raw, display: roundPackage(raw, policy || "none"), source: "calculated", missing: [] };
  }

  /* ── The label contract ───────────────────────────────────────────── */

  var STATES = ["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"];
  var STATE_NAMES = { AUSTRALIANCAPITALTERRITORY: "ACT", NEWSOUTHWALES: "NSW",
    NORTHERNTERRITORY: "NT", QUEENSLAND: "QLD", SOUTHAUSTRALIA: "SA",
    TASMANIA: "TAS", VICTORIA: "VIC", WESTERNAUSTRALIA: "WA" };
  var TOP_FIELDS = { order_number: [false, 24], job_number: [false, 28],
    customer_name: [true, 90], address_line_1: [true, 100],
    address_line_2: [false, 100], suburb: [true, 45], state: [true, null],
    postcode: [true, null], contact_name: [false, 55],
    contact_phone: [false, 30], items: [true, null] };
  var ITEM_FIELDS = ["width_mm", "height_mm", "depth_mm", "quantity",
    "product_type", "wrap_quantities", "max_per_wrap", "wrap_weights_kg",
    "packaging_weights_kg", "complete_filter_weight_kg_per_filter",
    "wrap_ids", "wrap_groups", "profile_refs", "packing_status", "description"];
  var REMOVED_FIELDS = ["fax", "purchase_order_number", "po_number",
    "dispatch_date", "delivery_instructions"];
  function LabelError(problems) {
    this.name = "LabelError"; this.problems = problems; this.message = problems.join("; ");
  }
  LabelError.prototype = Object.create(Error.prototype);

  function jobText(v) { var t = v === null || v === undefined ? "" : String(v).trim(); return t || "N/A"; }
  function normaliseState(v) {
    var k = String(v || "").toUpperCase().replace(/[^A-Z]/g, "");
    if (STATES.indexOf(k) !== -1) { return k; }
    return STATE_NAMES[k] || "";
  }
  function sizeText(w, h, d) {
    var parts = [w, h].concat(d ? [d] : []);
    return parts.map(function (p) { return String(p); }).join(" × ") + " mm";
  }
  function validateLabels(order) {
    var problems = [];
    if (!order || typeof order !== "object" || Array.isArray(order)) { throw new LabelError(["the order has to be an object"]); }
    Object.keys(order).forEach(function (k) {
      if (REMOVED_FIELDS.indexOf(k) !== -1) { problems.push(k + " is not printed on delivery labels"); }
      else if (!(k in TOP_FIELDS)) { problems.push(k + " is not a label field"); }
    });
    var clean = {};
    Object.keys(TOP_FIELDS).forEach(function (k) {
      if (k === "items") { return; }
      var spec = TOP_FIELDS[k], v = order[k];
      if (k === "job_number" && (v === null || v === undefined)) { clean[k] = null; return; }
      if (v === null || v === undefined) { v = ""; }
      if (typeof v !== "string") { problems.push(k + " has to be text (so leading zeros survive)"); return; }
      v = v.trim();
      if (spec[0] && !v) { problems.push(k + " is required"); }
      if (spec[1] && v.length > spec[1]) { problems.push(k + " is longer than " + spec[1] + " characters"); }
      clean[k] = v;
    });
    if (clean.state) {
      var st = normaliseState(clean.state);
      if (!st) { problems.push("state " + JSON.stringify(clean.state) + " is not an Australian state or territory"); }
      clean.state = st;
    }
    if (clean.postcode && !/^[0-9]{4}$/.test(clean.postcode)) { problems.push("postcode has to be four digits"); }
    var items = order.items;
    if (!Array.isArray(items) || !items.length) { problems.push("there has to be at least one item"); items = []; }
    clean.items = items.map(function (it, i) { return validateItem(it, i + 1, problems); });
    if (problems.length) { throw new LabelError(problems); }
    return clean;
  }
  function validateItem(it, i, problems) {
    var where = "line " + i;
    if (!it || typeof it !== "object" || Array.isArray(it)) { problems.push(where + " has to be an object"); return {}; }
    Object.keys(it).forEach(function (k) {
      if (REMOVED_FIELDS.indexOf(k) !== -1) { problems.push(where + ": " + k + " is not printed on labels"); }
      else if (ITEM_FIELDS.indexOf(k) === -1) { problems.push(where + ": " + k + " is not a label field"); }
    });
    var out = clone(it);
    var desc = it.description;
    if (desc !== null && desc !== undefined && typeof desc !== "string") {
      problems.push(where + ": description has to be text");
    }
    var described = typeof desc === "string" && desc.trim() !== "" &&
      ["width_mm", "height_mm", "depth_mm"].every(function (k) { return it[k] === null || it[k] === undefined; });
    ["width_mm", "height_mm", "depth_mm"].forEach(function (k) {
      if (described) { out[k] = null; return; }
      if (k === "depth_mm" && (it[k] === null || it[k] === undefined) &&
          String(it.product_type || "") === "Mounting Frame") { out[k] = null; return; }
      if (typeof it[k] === "boolean" || typeof it[k] === "string" || positive(it[k]) === null) {
        problems.push(where + ": " + k + " has to be a number above zero");
      } else { out[k] = positive(it[k]); }
    });
    var qty = it.quantity;
    if (typeof qty === "string" || positiveInt(qty) === null) {
      problems.push(where + ": quantity has to be a whole number of 1 or more");
      return out;
    }
    out.quantity = qty;
    var resolved = null;
    try {
      resolved = resolveQuantities(qty, it.wrap_quantities === undefined ? null : it.wrap_quantities,
                                   it.max_per_wrap === undefined ? null : it.max_per_wrap);
    } catch (e) { problems.push(where + ": " + e.message); resolved = null; }
    out._resolved = resolved;
    [["wrap_weights_kg", positive], ["packaging_weights_kg", nonNegative]].forEach(function (pair) {
      var arr = it[pair[0]];
      if (arr === null || arr === undefined) { return; }
      if (!Array.isArray(arr)) { problems.push(where + ": " + pair[0] + " has to be a list"); return; }
      arr.forEach(function (v, j) {
        if (v !== null && (typeof v === "boolean" || typeof v === "string" || pair[1](v) === null)) {
          problems.push(where + ": " + pair[0] + " entry " + (j + 1) + " has to be " +
            (pair[1] === positive ? "a number above zero" : "zero or more"));
        }
      });
      if (resolved !== null && arr.length !== resolved.length) {
        problems.push(where + ": " + pair[0] + " has " + arr.length + " entries for " + resolved.length + " wraps");
      }
    });
    var unit = it.complete_filter_weight_kg_per_filter;
    if (unit !== null && unit !== undefined && (typeof unit === "boolean" || typeof unit === "string" || nonNegative(unit) === null)) {
      problems.push(where + ": complete_filter_weight_kg_per_filter has to be zero or more");
    }
    return out;
  }
  // skipLines (1-based): lines that get no labels (bag filters). They still
  // count in the numbering, so line 3 of 4 is "3/4" either way.
  function buildLabels(order, base, settings, skipLines) {
    var skip = {};
    (skipLines || []).forEach(function (n) { skip[n] = true; });
    var clean = validateLabels(order);
    var s = settings || settingsDefaults();
    var packaging = s.packaging, policy = s.shipping_rounding || "none";
    var max = Number(s.max_bundle_kg) || MAX_BUNDLE_KG;
    var problems = [], perLine = [];
    clean.items.forEach(function (it, idx) {
      if (skip[idx + 1]) { perLine.push(null); return; }
      var unit = finite(it.complete_filter_weight_kg_per_filter);
      var qs = it._resolved;
      if (qs === null || qs === undefined) {
        var hp = handlingLimit(it.width_mm, it.height_mm, it.depth_mm, "", s.handling_profiles);
        var prop = propose(it.quantity, unit, packaging, hp ? hp.max_per_wrap : null, null, null, max,
                           s.default_max_per_wrap);
        if (!prop.wraps.length) { problems.push("line " + (idx + 1) + ": " + prop.issues.join("; ")); perLine.push([]); return; }
        qs = prop.wraps.map(function (w) { return w.quantity; });
      }
      var weights = it.wrap_weights_kg || qs.map(function () { return null; });
      var packs = it.packaging_weights_kg || qs.map(function () { return null; });
      var ids = it.wrap_ids || qs.map(function () { return null; });
      var groups = it.wrap_groups || qs.map(function () { return null; });
      perLine.push(qs.map(function (q, j) {
        var wrap = { quantity: q, measured_weight_kg: weights[j] };
        if (packs[j] !== null && packs[j] !== undefined) { wrap.packaging_weight_kg = packs[j]; wrap.packaging_confirmed = true; }
        return { quantity: q, id: ids[j], group: groups[j],
                 weight: resolveWrapWeight(wrap, unit, packaging, policy) };
      }));
    });
    if (problems.length) { throw new LabelError(problems); }
    var codes = wrapCodes(perLine.map(function (w) { return w === null ? 1 : w.length; }));
    var addr = [clean.address_line_1].concat(clean.address_line_2 ? [clean.address_line_2] : []);
    var labels = [];
    clean.items.forEach(function (it, i) {
      (perLine[i] || []).forEach(function (wrap, j) {
        labels.push({ company: COMPANY.name, abn: COMPANY.abn, phone: COMPANY.phone,
          from_address: base, customer_name: clean.customer_name,
          address_lines: addr, locality: clean.suburb + "  " + clean.state + "  " + clean.postcode,
          filter_size: it.width_mm === null && it.description ? it.description.trim()
            : sizeText(it.width_mm, it.height_mm, it.depth_mm),
          described: it.width_mm === null,
          wrap_quantity: wrap.quantity, line_quantity: it.quantity,
          weight_kg: wrap.weight.display, weight_source: wrap.weight.source,
          weight_raw_kg: wrap.weight.raw_kg, weight_missing: wrap.weight.missing,
          wrap_page: codes[i][j], contact_name: clean.contact_name || "",
          contact_phone: clean.contact_phone || "", order_number: clean.order_number || "",
          job_number: jobText(clean.job_number), group: wrap.group || "",
          wrap_id: wrap.id === undefined ? null : wrap.id, line: i + 1 });
      });
    });
    return labels;
  }

  /* ── C-channel (taf_order_app/cchannel.py) ───────────────────────── */

  var CCH_VERSION = "TAF-CCHANNEL-2026-10";
  var CCH_DEFAULT_MATERIAL = "C_CHANNEL_G2_Z275_055";
  var CCH_STACKS = [1, 2, 5, 10];
  var ZINC_DENSITY_KG_M3 = 7140;
  var CCH_SUPPLIED = [[15, 13], [20, 18], [25, 22], [30, 28], [35, 33], [40, 38],
    [45, 44], [50, 48], [55, 53], [60, 58], [65, 63], [70, 68], [75, 74], [80, 78],
    [85, 84], [90, 89], [95, 94], [100, 98]];
  var CCH_VERIFIED = "verified", CCH_SUPPLIED_S = "supplied_unconfirmed_mapping",
      CCH_ESTIMATED = "estimated", CCH_PROVISIONAL = "provisional_estimate",
      CCH_CUSTOM = "custom";
  var CCH_STATUS_LABELS = {};
  CCH_STATUS_LABELS[CCH_VERIFIED] = "Verified";
  CCH_STATUS_LABELS[CCH_SUPPLIED_S] = "Supplied, unconfirmed";
  CCH_STATUS_LABELS[CCH_ESTIMATED] = "Estimated";
  CCH_STATUS_LABELS[CCH_PROVISIONAL] = "Provisional estimate";
  CCH_STATUS_LABELS[CCH_CUSTOM] = "Custom";

  function cChannelDefaults() {
    var widths = { "10": { width_mm: 10, status: CCH_PROVISIONAL,
                           source: "initial estimate - confirm" } };
    CCH_SUPPLIED.forEach(function (p) {
      widths[String(p[0])] = { width_mm: p[1], status: CCH_SUPPLIED_S,
        source: "TAF measurement; nominal depth inferred from the sequence" };
    });
    var mats = {};
    mats[CCH_DEFAULT_MATERIAL] = {
      material_code: CCH_DEFAULT_MATERIAL, material: "G2 Z275 galvanised steel",
      steel_grade: "G2", galvanising: "Z275", nominal_thickness_mm: 0.55,
      thickness_basis: "nominal_supplied", base_metal_thickness_mm: null,
      coating_mass_g_m2: 275, include_coating_mass: false, density_kg_m3: 7850,
      stock_length_mm: 2440, left_flange_mm: 23, right_flange_mm: 23,
      bend_correction_mm: 0, mass_calibration_factor: null };
    return { version: CCH_VERSION, default_material: CCH_DEFAULT_MATERIAL,
      materials: mats, depth_range: { min_mm: 10, max_mm: 250, step_mm: 5 },
      estimate_rule: { subtract_mm: 2 }, centre_widths: widths,
      measured_weights: [], stack_quantities: CCH_STACKS.slice(), rounding: "up_0.1" };
  }
  function cchKey(depth) {
    var d = finite(depth);
    return d === null ? "" : String(d);
  }
  function cChannelMerged(stored) {
    var out = cChannelDefaults();
    if (!stored || typeof stored !== "object" || Array.isArray(stored)) { return out; }
    Object.keys(stored).forEach(function (key) {
      var value = stored[key];
      if (key === "materials" && value && typeof value === "object") {
        Object.keys(value).forEach(function (code) {
          var base = clone(out.materials[code] || {});
          var m = value[code] || {};
          Object.keys(m).forEach(function (k) { base[k] = m[k]; });
          base.material_code = code;
          out.materials[code] = base;
        });
      } else if (key === "centre_widths" && value && typeof value === "object") {
        Object.keys(value).forEach(function (d) {
          if (value[d] && typeof value[d] === "object") { out.centre_widths[cchKey(d)] = clone(value[d]); }
        });
      } else if (value !== null && value !== undefined) {
        out[key] = clone(value);
      }
    });
    return out;
  }
  function cchSettings(settings) {
    if (settings === null || settings === undefined) { return cChannelDefaults(); }
    if (typeof settings === "object" && "c_channel" in settings) { return cChannelMerged(settings.c_channel); }
    return cChannelMerged(settings);
  }
  function cChannelDepths(settings) {
    var r = cchSettings(settings).depth_range;
    var lo = positive(r.min_mm) || 10, hi = positive(r.max_mm) || 250, step = positive(r.step_mm) || 5;
    var out = [], d = lo;
    while (d <= hi + 1e-9) { out.push(d); d += step; }
    return out;
  }
  function roundUpKg(kg) {
    if (kg === null || kg === undefined) { return null; }
    return Math.ceil(round9(kg * 10)) / 10;
  }
  function kgTextOne(kg) { return kg === null || kg === undefined ? "" : kg.toFixed(1) + " kg"; }
  function cChannelMaterial(settings, code) {
    var s = cchSettings(settings);
    var c = String(code || s.default_material || CCH_DEFAULT_MATERIAL);
    var m = (s.materials || {})[c];
    if (!m) { return null; }
    var out = clone(m); out.material_code = c;
    return out;
  }
  function blankish(v) { return v === null || v === undefined || v === ""; }

  function resolveCChannelDimensions(nominalDepth, centreWidth, settings, materialCode, length, left, right) {
    var s = cchSettings(settings);
    var out = { calculation_status: "ok", material_code: null, nominal_depth_mm: null,
      actual_centre_width_mm: null, left_flange_mm: null, right_flange_mm: null,
      channel_length_mm: null, dimension_source: null, verification_status: null,
      missing_inputs: [], validation_errors: [], calculation_warnings: [] };
    var errors = out.validation_errors, warnings = out.calculation_warnings;
    var mat = cChannelMaterial(s, materialCode);
    if (mat === null) {
      errors.push("there is no C-channel material '" + materialCode + "'");
      out.calculation_status = "invalid_input";
      return out;
    }
    out.material_code = mat.material_code;
    function pos(value, label) {
      var v = positive(value);
      if (v === null) { errors.push(label + " must be a number above zero"); }
      return v;
    }
    var depth = null;
    if (!blankish(nominalDepth)) { depth = pos(nominalDepth, "nominal depth"); }
    out.nominal_depth_mm = depth;
    if (!blankish(centreWidth)) {
      out.actual_centre_width_mm = pos(centreWidth, "centre width");
      out.dimension_source = "custom";
      out.verification_status = CCH_CUSTOM;
    } else if (depth !== null) {
      var row = (s.centre_widths || {})[cchKey(depth)];
      var width = positive((row || {}).width_mm);
      if (row && width !== null) {
        var status = String(row.status || CCH_ESTIMATED);
        if (!(status in CCH_STATUS_LABELS)) { status = CCH_ESTIMATED; }
        out.actual_centre_width_mm = width;
        out.verification_status = status;
        out.dimension_source = status === CCH_VERIFIED ? "verified_measurement"
          : status === CCH_SUPPLIED_S ? "supplied_measurement"
          : status === CCH_CUSTOM ? "custom" : "estimated_rule";
      } else {
        var sub = finite((s.estimate_rule || {}).subtract_mm);
        if (sub === null) { sub = 2; }
        var w = depth - sub;
        if (w <= 0) {
          errors.push("a " + depth + "mm depth less " + sub + "mm leaves no centre width - enter one");
        } else {
          out.actual_centre_width_mm = w;
          out.dimension_source = "estimated_rule";
          out.verification_status = CCH_ESTIMATED;
        }
      }
      if (out.verification_status === CCH_ESTIMATED || out.verification_status === CCH_PROVISIONAL) {
        warnings.push("the centre width for " + depth + "mm is an estimate - confirm it");
      } else if (out.verification_status === CCH_SUPPLIED_S) {
        warnings.push("the " + out.actual_centre_width_mm + "mm centre width for " + depth +
          "mm is a supplied measurement whose depth match is not yet confirmed");
      }
    } else if (!errors.length) {
      out.missing_inputs.push("a nominal depth or a centre width");
    }
    out.left_flange_mm = pos(blankish(left) ? mat.left_flange_mm : left, "left flange");
    out.right_flange_mm = pos(blankish(right) ? mat.right_flange_mm : right, "right flange");
    out.channel_length_mm = pos(blankish(length) ? mat.stock_length_mm : length, "channel length");
    if (errors.length) { out.calculation_status = "invalid_input"; }
    else if (out.missing_inputs.length) { out.calculation_status = "needs_input"; }
    return out;
  }
  function cChannelSizeText(d) {
    var parts = [d.left_flange_mm, d.actual_centre_width_mm, d.right_flange_mm, d.channel_length_mm];
    if (parts.some(function (p) { return p === null || p === undefined; })) { return ""; }
    return parts.map(String).join(" x ") + " mm";
  }
  function nonNegOrNull(v) { var n = finite(v); return n !== null && n >= 0 ? n : null; }
  function cchThickness(mat, errors) {
    var basis = String(mat.thickness_basis || "nominal_supplied");
    var base = positive(mat.base_metal_thickness_mm);
    if (base !== null) { return base; }
    var nominal = positive(mat.nominal_thickness_mm);
    if (nominal === null) { errors.push("material thickness must be a number above zero"); return null; }
    if (basis === "coated") {
      var coat = nonNegOrNull(mat.coating_mass_g_m2);
      if (coat === null) { errors.push("a coated thickness needs the coating mass"); return null; }
      var t = nominal - coat / ZINC_DENSITY_KG_M3;
      if (t <= 0) { errors.push("the coating is thicker than the steel"); return null; }
      return t;
    }
    return nominal;
  }
  function cchMeasured(s, code, dims) {
    var list = s.measured_weights || [];
    for (var i = 0; i < list.length; i++) {
      var m = list[i];
      if (!m.verified || String(m.material_code || code) !== code) { continue; }
      var kg = positive(m.kg), len = positive(m.length_mm);
      if (kg === null || len === null) { continue; }
      var width = positive(m.centre_width_mm), depth = positive(m.nominal_depth_mm);
      if (width !== null) {
        if (Math.abs(width - (dims.actual_centre_width_mm || -1)) > 1e-9) { continue; }
      } else if (depth === null || dims.nominal_depth_mm === null ||
                 Math.abs(depth - dims.nominal_depth_mm) > 1e-9) { continue; }
      var out = clone(m); out.kg = kg; out.length_mm = len;
      return out;
    }
    return null;
  }
  function calculateCChannelWeight(nominalDepth, centreWidth, length, settings, materialCode,
                                   left, right, useMeasured) {
    var s = cchSettings(settings);
    var out = resolveCChannelDimensions(nominalDepth, centreWidth, s, materialCode, length, left, right);
    out.material_thickness_mm = null; out.steel_density_kg_m3 = null;
    out.developed_width_mm = null; out.weight_basis = null; out.weight_per_mm_kg = null;
    out.raw_weight_kg = null; out.display_weight_kg = null; out.settings_version = s.version;
    if (out.calculation_status !== "ok") { return out; }
    var errors = out.validation_errors, warnings = out.calculation_warnings;
    var mat = cChannelMaterial(s, out.material_code) || {};
    var t = cchThickness(mat, errors);
    var density = positive(mat.density_kg_m3);
    if (density === null) { errors.push("steel density must be a number above zero"); }
    var bend = finite(mat.bend_correction_mm);
    if (bend === null && !blankish(mat.bend_correction_mm)) { errors.push("the bend correction must be a number"); }
    var developed = out.left_flange_mm + out.actual_centre_width_mm + out.right_flange_mm + (bend || 0);
    if (developed <= 0) { errors.push("the developed width comes out at nothing"); }
    if (errors.length) { out.calculation_status = "invalid_input"; return out; }
    out.material_thickness_mm = t; out.steel_density_kg_m3 = density; out.developed_width_mm = developed;
    var len = out.channel_length_mm, perMm;
    var measured = useMeasured === false ? null : cchMeasured(s, out.material_code, out);
    if (measured !== null) {
      perMm = measured.kg / measured.length_mm;
      out.weight_basis = "measured";
      if (Math.abs(measured.length_mm - len) > 1e-9) {
        out.weight_basis = "measured_scaled_to_length";
        warnings.push("measured over " + measured.length_mm + "mm, scaled to " + len + "mm");
      }
    } else {
      perMm = developed * t * density / 1e9;
      var basis = "calculated_base_steel";
      var coat = nonNegOrNull(mat.coating_mass_g_m2);
      if (mat.include_coating_mass) {
        var confirmed = !blankish(mat.base_metal_thickness_mm) ||
          mat.thickness_basis === "base_metal" || mat.thickness_basis === "coated";
        if (confirmed && coat !== null) {
          perMm += developed * coat / 1e9;
          basis = "calculated_steel_and_coating";
        } else {
          warnings.push("coating not added: the 0.55mm may already include it until the steel's base-metal thickness is confirmed");
        }
      }
      var cal = positive(mat.mass_calibration_factor);
      if (cal !== null) { perMm *= cal; basis += "_calibrated"; }
      out.weight_basis = basis;
    }
    out.weight_per_mm_kg = perMm;
    out.raw_weight_kg = perMm * len;
    out.display_weight_kg = roundUpKg(out.raw_weight_kg);
    return out;
  }
  function calculateCChannelStackWeights(channel, quantities) {
    var qs = quantities === undefined || quantities === null ? CCH_STACKS.slice() : quantities;
    var raw = channel.raw_weight_kg;
    return qs.map(function (q) {
      var n = positiveInt(q);
      if (n === null) {
        return { stack_quantity: q, stack_raw_weight_kg: null, stack_display_weight_kg: null,
                 validation_errors: ["a stack is a whole number of 1 or more lengths"] };
      }
      var total = raw === null || raw === undefined ? null : raw * n;
      return { stack_quantity: n, stack_raw_weight_kg: total,
               stack_display_weight_kg: roundUpKg(total), validation_errors: [] };
    });
  }
  function calculateCChannelCutSectionWeight(channel, cutLength, sectionQuantity, measuredKg) {
    var out = { cut_length_mm: positive(cutLength),
      section_quantity: positiveInt(sectionQuantity === undefined ? 1 : sectionQuantity),
      section_weight_kg: null, weight_basis: null, validation_errors: [] };
    if (out.cut_length_mm === null) { out.validation_errors.push("a cut length must be above zero"); }
    if (out.section_quantity === null) { out.validation_errors.push("a section count is a whole number of 1 or more"); }
    if (out.validation_errors.length) { return out; }
    var m = positive(measuredKg);
    if (m !== null) { out.section_weight_kg = m; out.weight_basis = "measured"; return out; }
    var perMm = channel.weight_per_mm_kg;
    if (perMm === null || perMm === undefined) { return out; }
    out.section_weight_kg = perMm * out.cut_length_mm * out.section_quantity;
    out.weight_basis = channel.weight_basis;
    return out;
  }

  // cutting.layout, for the frame's cut list: U / Sideways U a strip and a
  // cap, G one strip, L two strips (long, short, lip).
  var FRAME_NAMES = { u: "U", sideways_u: "Sideways U", g: "G", l: "L" };
  var FRAME_STRIPS = { u: 1, sideways_u: 1, g: 1, l: 2 };
  function frameLayout(short, long, method) {
    if (!(method in FRAME_NAMES)) { return null; }
    var sh = finite(short), lo = finite(long);
    if (sh === null || lo === null || sh <= 0 || lo <= 0) { return null; }
    var lip = 20, allow = 2;
    var s = sh - allow, l = lo - allow;
    if (s <= 0 || l <= 0) { return null; }
    var segs, cap;
    if (method === "u") { segs = [lip, s, l, s, lip]; cap = l; }
    else if (method === "sideways_u") { segs = [lip, l, s, l, lip]; cap = s; }
    else if (method === "l") { segs = [l, s, lip]; cap = 0; }
    else { segs = [l, s, l, s, lip]; cap = 0; }
    return { name: FRAME_NAMES[method], frame: sum(segs), cap: cap, strips: FRAME_STRIPS[method] };
  }
  function frameCutList(short, long, method, nominalDepth, materialCode) {
    var shape = frameLayout(short, long, method || "u");
    if (shape === null) { return null; }
    var rows = [{ name: shape.name + " strip", cut_length_mm: shape.frame,
                  section_quantity: shape.strips }];
    if (shape.cap) { rows.push({ name: "cap", cut_length_mm: shape.cap, section_quantity: 1 }); }
    rows.forEach(function (r) {
      r.nominal_depth_mm = nominalDepth === undefined ? null : nominalDepth;
      r.material_code = materialCode || CCH_DEFAULT_MATERIAL;
    });
    return rows;
  }
  function calculateCChannelFrameWeight(cutList, orderQuantity, settings) {
    var s = cchSettings(settings);
    var out = { calculation_status: "ok", sections: [], frame_weight_kg: null,
      frame_weight_kg_order: null,
      order_quantity: positiveInt(orderQuantity === undefined ? 1 : orderQuantity),
      missing_inputs: [], validation_errors: [], calculation_warnings: [],
      settings_version: s.version };
    var rows = cutList || [];
    if (!rows.length) {
      out.calculation_status = "needs_frame_cut_rule";
      out.missing_inputs.push("a verified frame cut list (cut lengths and how many of each per filter)");
      return out;
    }
    if (out.order_quantity === null) { out.validation_errors.push("the order quantity is a whole number of 1 or more"); }
    var total = 0;
    rows.forEach(function (row, i) {
      var ch = calculateCChannelWeight(row.nominal_depth_mm, row.centre_width_mm, null, s, row.material_code);
      var sec = calculateCChannelCutSectionWeight(ch, row.cut_length_mm,
        row.section_quantity === undefined ? 1 : row.section_quantity, row.measured_kg);
      sec.name = row.name || ("section " + (i + 1));
      sec.nominal_depth_mm = ch.nominal_depth_mm;
      sec.actual_centre_width_mm = ch.actual_centre_width_mm;
      sec.verification_status = ch.verification_status;
      sec.material_code = ch.material_code;
      out.sections.push(sec);
      ch.validation_errors.concat(sec.validation_errors).forEach(function (e) { out.validation_errors.push(sec.name + ": " + e); });
      ch.missing_inputs.forEach(function (m) { out.missing_inputs.push(sec.name + ": " + m); });
      ch.calculation_warnings.forEach(function (w) {
        if (out.calculation_warnings.indexOf(w) === -1) { out.calculation_warnings.push(w); }
      });
      if (sec.section_weight_kg === null) { total = null; }
      else if (total !== null) { total += sec.section_weight_kg; }
    });
    if (out.validation_errors.length) { out.calculation_status = "invalid_input"; return out; }
    if (total === null) { out.calculation_status = "needs_input"; return out; }
    out.calculation_warnings.push("corner notches and trimmed lip flanges are not deducted (their size is not confirmed), so this errs heavy");
    out.frame_weight_kg = total;
    out.frame_weight_kg_order = total * out.order_quantity;
    return out;
  }
  function calculateCChannelStockWeight(nominalDepth, lengths, length, centreWidth, settings, materialCode) {
    var ch = calculateCChannelWeight(nominalDepth, centreWidth, length, settings, materialCode);
    var out = clone(ch);
    var n = positiveInt(lengths === undefined ? 1 : lengths);
    if (n === null) {
      out.validation_errors = ch.validation_errors.concat(["a number of lengths is a whole number of 1 or more"]);
      out.calculation_status = "invalid_input";
    }
    out.stack_quantity = n;
    var raw = ch.raw_weight_kg;
    out.stack_raw_weight_kg = raw === null || n === null ? null : raw * n;
    out.stack_display_weight_kg = roundUpKg(out.stack_raw_weight_kg);
    return out;
  }
  function cChannelTable(settings, quantities) {
    var s = cchSettings(settings);
    var qs = quantities === undefined || quantities === null ? (s.stack_quantities || CCH_STACKS) : quantities;
    return cChannelDepths(s).map(function (d) {
      var ch = calculateCChannelWeight(d, null, null, s);
      return { nominal_depth_mm: d, actual_centre_width_mm: ch.actual_centre_width_mm,
        size: cChannelSizeText(ch), verification_status: ch.verification_status,
        dimension_source: ch.dimension_source, weight_basis: ch.weight_basis,
        raw_weight_kg: ch.raw_weight_kg, stacks: calculateCChannelStackWeights(ch, qs),
        calculation_status: ch.calculation_status };
    });
  }


  var api = {
    // numbers
    positiveInt: positiveInt, positive: positive, finite: finite, pyRound: pyRound,
    // materials
    DEFAULTS_VERSION: DEFAULTS_VERSION, MaterialError: MaterialError,
    normaliseMediaCode: normaliseMediaCode, normaliseWireCode: normaliseWireCode,
    materialDefaults: materialDefaults, wireMaterial: wireMaterial,
    mediaMaterial: mediaMaterial, selectWire: selectWire,
    // settings
    BASE_ADDRESS_DEFAULT: BASE_ADDRESS_DEFAULT, COMPANY: COMPANY,
    MAX_BUNDLE_KG: MAX_BUNDLE_KG, settingsDefaults: settingsDefaults,
    mergeSettings: mergeSettings, baseAddress: baseAddress,
    // bracing and frames
    bracing: bracing, braceShortLabel: braceShortLabel,
    mountingFrame: mountingFrame, mountingFrameProfile: mountingFrameProfile,
    // calculator
    CALC_VERSION: CALC_VERSION, FILTER_TYPE_WORDINGS: FILTER_TYPE_WORDINGS,
    BUILTIN_PROFILES: BUILTIN_PROFILES, constructionOf: constructionOf,
    profileCut: profileCut, calculate: calculate, requestFromItem: requestFromItem,
    calculateItem: function (item, s) { return calculate(requestFromItem(item), s); },
    // packing
    PackingError: PackingError, split: split, checkQuantities: checkQuantities,
    resolveQuantities: resolveQuantities, letters: letters, wrapCodes: wrapCodes,
    packagingKg: packagingKg, weightCapacity: weightCapacity,
    handlingLimit: handlingLimit, propose: propose, checkPlan: checkPlan,
    instruction: instruction, planInstructions: planInstructions,
    // labels
    LabelError: LabelError, roundPackage: roundPackage,
    resolveWrapWeight: resolveWrapWeight, validateLabels: validateLabels,
    buildLabels: buildLabels, jobText: jobText,
    // C-channel
    C_CHANNEL_VERSION: CCH_VERSION, C_CHANNEL_STATUS_LABELS: CCH_STATUS_LABELS,
    cChannelDefaults: cChannelDefaults, cChannelMerged: cChannelMerged,
    cChannelDepths: cChannelDepths, roundUpKg: roundUpKg, kgText: kgTextOne,
    resolveCChannelDimensions: resolveCChannelDimensions,
    calculateCChannelWeight: calculateCChannelWeight,
    calculateCChannelStackWeights: calculateCChannelStackWeights,
    calculateCChannelCutSectionWeight: calculateCChannelCutSectionWeight,
    calculateCChannelFrameWeight: calculateCChannelFrameWeight,
    calculateCChannelStockWeight: calculateCChannelStockWeight,
    cChannelTable: cChannelTable, cChannelSizeText: cChannelSizeText,
    frameCutList: frameCutList
  };

  root.TAFCALC = api;
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
})(typeof globalThis !== "undefined" ? globalThis : this);
