/*
  Shared by the quote page and the customer portal: the masthead logo, the
  contact footer, and the line about never asking for payment details.

  Both pages ask a customer to act on a link that arrived by email, which is
  exactly what a phishing message looks like. Everything here exists to make
  the page obviously TAF's and to give the reader a person to ring.
*/
"use strict";

var TAF = (function () {
  var C = window.TAF_COMPANY || {};

  function has(v) { return typeof v === "string" && v.trim() !== ""; }

  /* A logo in the masthead. Falls back silently to the wordmark that is
     already there if the image is missing, rather than leaving a broken
     icon on a page about money. */
  function logo(headerEl, depth) {
    if (!headerEl) { return; }
    var img = document.createElement("img");
    img.src = (depth || "../") + "taf-logo.png";
    img.alt = C.name || "Total Air Filtration";
    img.className = "taf-logo";
    img.onerror = function () { img.remove(); };
    headerEl.insertBefore(img, headerEl.firstChild);
    headerEl.classList.add("has-logo");
  }

  function line(parent, text, href) {
    if (!has(text)) { return; }
    var el = document.createElement(href ? "a" : "span");
    el.textContent = text;
    if (href) { el.href = href; }
    parent.appendChild(el);
  }

  /* Who we are and how to reach us. Rendered even when a link is broken,
     because that is exactly when someone needs to ring. */
  function footer(el) {
    if (!el) { return; }
    el.innerHTML = "";
    el.className = "taf-footer";

    var name = document.createElement("strong");
    name.textContent = C.name || "Total Air Filtration";
    el.appendChild(name);

    var contact = document.createElement("div");
    contact.className = "taf-contact";
    // Tappable on a phone, which is where most of these are opened.
    line(contact, C.phone, has(C.phone) ? "tel:" + C.phone.replace(/\s+/g, "") : null);
    line(contact, C.email, has(C.email) ? "mailto:" + C.email : null);
    line(contact, C.website && C.website.replace(/^https?:\/\//, ""),
         has(C.website) ? C.website : null);
    if (contact.childNodes.length) { el.appendChild(contact); }

    var detail = document.createElement("div");
    detail.className = "taf-detail";
    line(detail, C.address);
    line(detail, C.hours);
    line(detail, has(C.abn) ? "ABN " + C.abn : "");
    if (detail.childNodes.length) { el.appendChild(detail); }

    var safety = document.createElement("p");
    safety.className = "taf-safety";
    safety.textContent =
      "We will never ask for card or bank details on this page. If anything " +
      "here looks wrong, ring us before acting on it.";
    el.appendChild(safety);
  }

  /* "Ready for pick up" is only useful with an address and opening hours. */
  function pickupNote() {
    var p = C.pickup || {};
    var bits = [];
    if (has(p.address)) { bits.push("Collect from " + p.address.trim() + "."); }
    if (has(p.hours))   { bits.push(p.hours.trim() + "."); }
    if (has(p.note))    { bits.push(p.note.trim()); }
    return bits.join(" ");
  }

  function askUs(subject) {
    if (has(C.email)) {
      return { href: "mailto:" + C.email +
                     "?subject=" + encodeURIComponent(subject), label: C.email };
    }
    if (has(C.phone)) {
      return { href: "tel:" + C.phone.replace(/\s+/g, ""), label: C.phone };
    }
    return null;
  }

  return { company: C, logo: logo, footer: footer,
           pickupNote: pickupNote, askUs: askUs, has: has };
})();
