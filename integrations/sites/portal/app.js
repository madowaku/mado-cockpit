"use strict";
const grid = document.getElementById("projectGrid");
const filters = document.getElementById("filters");
const search = document.getElementById("search");
const empty = document.getElementById("empty");
const resultCount = document.getElementById("resultCount");
const loadError = document.getElementById("loadError");
let allProjects = [];
let category = "All";
const palette = {Control:["#a2f6bb","◎"],Assets:["#99c9fc","◇"],Games:["#f2c9a1","✦"],Audio:["#e8b6fa","♫"],Quality:["#9fe5dc","▦"],Experiences:["#e1ef9d","✳"],Research:["#bdb9ff","∿"]};
const states = {source_only:"SOURCE ONLY",preview_pending:"REVIEW PENDING",published_verified:"LIVE VERIFIED"};
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
  art.append(element("span", "visual-index", String(i+1).padStart(2, "0") + " / MADO"));
  art.append(element("span", "visual-glyph", palette[project.category]?.[1] || "◈"));
  art.append(element("span", "visual-tag", project.visual.toUpperCase()));
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
