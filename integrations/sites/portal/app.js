"use strict";
const grid = document.getElementById("projectGrid");
const filters = document.getElementById("filters");
const search = document.getElementById("search");
const empty = document.getElementById("empty");
const resultCount = document.getElementById("resultCount");
const loadError = document.getElementById("loadError");
let allProjects = [];
let category = "All";
let galleryItems = [];
let galleryKind = "all";
const galleryGrid = document.getElementById("galleryGrid");
const galleryFilters = document.getElementById("galleryFilters");
const galleryCount = document.getElementById("galleryCount");
const galleryEmpty = document.getElementById("galleryEmpty");
const galleryError = document.getElementById("galleryError");
const galleryDialog = document.getElementById("galleryDialog");
const galleryKinds = {all:"ALL SOURCES",browser_golden:"E2E GOLDENS",marketing_asset:"MARKETING ASSETS"};
const galleryKindLabels = {browser_golden:"E2E GOLDEN / FIXTURE",marketing_asset:"MARKETING ASSET / SOURCE"};
function rawSource(item) {
  const s = item.source;
  return "https://raw.githubusercontent.com/" + s.repository + "/" + s.commit + "/" + s.path;
}
function sourceLink(item) {
  const s = item.source;
  return "https://github.com/" + s.repository + "/blob/" + s.commit + "/" + s.path;
}
function pickFeatured(projectId) {
  return galleryItems.find(item => item.project_id === projectId && item.featured);
}
function imgWithFallback(item, cssClass, fallback) {
  const img = element("img", cssClass);
  img.src = rawSource(item);
  img.alt = item.title + " (" + galleryKindLabels[item.kind] + ", visual review pending)";
  img.loading = "lazy";
  img.decoding = "async";
  img.referrerPolicy = "no-referrer";
  img.addEventListener("error", () => {
    img.hidden = true;
    if (fallback) fallback.hidden = false;
    if (cssClass === "card-photo" && img.parentNode) img.parentNode.classList.remove("has-photo");
  });
  return img;
}
const palette = {Control:["#a2f6bb","◎"],Assets:["#99c9fc","◇"],Games:["#f2c9a1","✦"],Audio:["#e8b6fa","♫"],Quality:["#9fe5dc","▦"],Experiences:["#e1ef9d","✳"],Research:["#bdb9ff","∿"]};
const states = {source_only:"SOURCE ONLY",preview_pending:"REVIEW PENDING",published_verified:"LIVE VERIFIED"};
const humanTestPilots = new Set(["mado-game-service-factory", "gear-relay", "mado-cockpit"]);
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function link(label, url) {
  const a = element("a", "", label);
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
function buildCard(project, i) {
  const card = element("article", "project-card");
  const art = element("div", "card-visual");
  art.style.setProperty("--accent", palette[project.category]?.[0] || "#aaccee");
  const featured = pickFeatured(project.id);
  if (featured) {
    art.classList.add("has-photo");
    art.append(imgWithFallback(featured, "card-photo"));
  }
  art.append(element("span", "visual-index", String(i+1).padStart(2, "0") + " / MADO"));
  art.append(element("span", "visual-glyph", palette[project.category]?.[1] || "◈"));
  art.append(element("span", "visual-tag", project.visual.toUpperCase()));
  if (featured) art.append(element("span", "evidence-pending", "SOURCE LOCATED / REVIEW PENDING"));
  card.append(art);
  const body = element("div", "card-body");
  const kicker = element("div", "card-kicker");
  kicker.append(element("span", "", project.category.toUpperCase()));
  if (project.featured) kicker.append(element("span", "", "FEATURED ↗"));
  body.append(kicker, element("h3", "", project.title), element("p", "", project.description));
  const foot = element("div", "card-foot");
  foot.append(element("span", "state" + (project.publication.state === "published_verified" ? " verified" : ""), states[project.publication.state]));
  const actions = element("div", "card-links");
  actions.append(link("GITHUB ↗", project.repository));
  if (humanTestPilots.has(project.id)) {
    const testLink = element("a", "", "3 MIN HUMAN TEST ↗");
    testLink.href = "./test-flight.html?project=" + encodeURIComponent(project.id);
    actions.append(testLink);
  }
  if (project.publication.state === "published_verified" && project.publication.url) actions.append(link("OPEN SITE ↗", project.publication.url));
  foot.append(actions);body.append(foot);card.append(body);
  return card;
}
function render() {
  const term = search.value.trim().toLocaleLowerCase("ja");
  const matches = allProjects.filter(p => (category === "All" || p.category === category) && [p.title,p.description,p.category,p.id].some(s=>s.toLocaleLowerCase("ja").includes(term)));
  grid.replaceChildren(...matches.map(buildCard));
  resultCount.textContent = String(matches.length).padStart(2, "0") + " PROJECTS / " + String(allProjects.length).padStart(2, "0") + " TOTAL";
  empty.hidden = matches.length !== 0;
  for (const btn of filters.querySelectorAll("button")) btn.setAttribute("aria-pressed", String(btn.dataset.category === category));
}
function renderFilters() {
  const categories = ["All",...new Set(allProjects.map(p=>p.category).sort())];
  filters.replaceChildren(...categories.map(c => {
    const b = element("button", "filter", c.toUpperCase());
    b.type = "button";b.dataset.category = c;
    b.setAttribute("aria-pressed",String(c===category));
    b.addEventListener("click",()=>{category=c;render();});
    return b;
  }));
}
function openGalleryDetail(item) {
  const img = document.getElementById("dialogImage");
  const error = document.getElementById("dialogImageError");
  document.getElementById("dialogTitle").textContent = item.title;
  document.getElementById("dialogDescription").textContent = item.description;
  document.getElementById("dialogKind").textContent = galleryKindLabels[item.kind] + " • COMMITTED SOURCE, NOT LIVE PROOF";
  document.getElementById("dialogSource").href = sourceLink(item);
  error.hidden = true;
  img.hidden = false;
  img.alt = item.title + " / visual inspection pending";
  img.onerror = () => {img.hidden = true;error.hidden = false;};
  img.src = rawSource(item);
  galleryDialog.showModal();
}
document.getElementById("dialogClose").addEventListener("click", () => galleryDialog.close());
galleryDialog.addEventListener("click", event => {
  if (event.target === galleryDialog) galleryDialog.close();
});
function galleryCard(item) {
  const article = element("article", "gallery-tile");
  const preview = element("button", "gallery-preview");
  preview.type = "button";
  preview.setAttribute("aria-label", item.title + "の出典付きプレビューを表示");
  const fallback = element("span", "gallery-fallback", "Image unavailable / source link remains available");
  fallback.hidden = true;
  preview.append(imgWithFallback(item, "gallery-image", fallback), fallback);
  preview.append(element("span", "gallery-source-flag", "SOURCE LOCATED · VISUAL REVIEW PENDING"));
  preview.addEventListener("click", () => openGalleryDetail(item));
  article.append(preview);
  const info = element("div", "gallery-tile-info");
  const meta = element("div");
  meta.append(element("h3", "", item.title), element("p", "gallery-kind", galleryKindLabels[item.kind]));
  info.append(meta, link("SOURCE ↗", sourceLink(item)));
  info.lastChild.className = "gallery-source";
  article.append(info);
  return article;
}
function renderGallery() {
  const visible = galleryItems.filter(item => galleryKind === "all" || item.kind === galleryKind);
  galleryGrid.replaceChildren(...visible.map(galleryCard));
  galleryCount.textContent = String(visible.length).padStart(2, "0") + " IMAGES / " + String(galleryItems.length).padStart(2,"0") + " SOURCES";
  galleryEmpty.hidden = visible.length > 0;
  galleryFilters.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed",String(b.dataset.kind === galleryKind)));
}
function renderGalleryFilters() {
  galleryFilters.replaceChildren(...Object.entries(galleryKinds).map(([kind,label]) => {
    const b = element("button", "filter", label);
    b.type = "button";b.dataset.kind = kind;
    b.setAttribute("aria-pressed", String(galleryKind === kind));
    b.addEventListener("click", () => {galleryKind=kind;renderGallery();});
    return b;
  }));
}
async function loadGallery() {
  try {
    const response = await fetch("./gallery.json", {cache:"no-store"});
    if (!response.ok) throw new Error("Gallery HTTP " + response.status);
    const manifest = await response.json();
    if (manifest.schema !== "mado.sites-gallery.v1" ||
        !Array.isArray(manifest.items) ||
        manifest.deployment_verified !== false ||
        manifest.visual_review !== "pending") throw new Error("Unexpected gallery review contract");
    galleryItems = manifest.items;
    renderGalleryFilters();
    renderGallery();
    render();
  } catch (err) {
    galleryCount.textContent = "GALLERY UNAVAILABLE";
    galleryError.hidden = false;
    console.error("Gallery manifest load failed", err);
  }
}
async function init() {
  try {
    const response = await fetch("./catalog.json", {cache:"no-store"});
    if (!response.ok) throw new Error("Catalog HTTP " + response.status);
    const catalog = await response.json();
    if (catalog.schema !== "mado.sites-catalog.v1" || !Array.isArray(catalog.projects)) throw new Error("Unexpected catalog schema");
    allProjects = catalog.projects;
    document.getElementById("snapshot").textContent = catalog.snapshot_date.replaceAll("-", ".");
    document.getElementById("projectCount").textContent = allProjects.length.toString().padStart(2,"0");
    document.getElementById("categoryCount").textContent = new Set(allProjects.map(p=>p.category)).size.toString().padStart(2,"0");
    document.getElementById("publishedCount").textContent = allProjects.filter(p=>p.publication.state==="published_verified").length.toString().padStart(2,"0");
    renderFilters();render();
    await loadGallery();
  } catch (err) {
    resultCount.textContent = "CATALOG UNAVAILABLE";
    loadError.hidden = false;
    console.error("MADO catalog load failed", err);
  }
}
search.addEventListener("input",render);
document.getElementById("reset").addEventListener("click",()=>{category="All";search.value="";render();search.focus();});
document.addEventListener("keydown",event=>{if(event.key==="/" && !["INPUT","TEXTAREA"].includes(document.activeElement.tagName)){event.preventDefault();search.focus();}});
init();
