import { createLibrary, defineComponent } from "@openuidev/react-lang";
import { z } from "zod/v4";

const rowSchema = z.object({
  title: z.string(),
  detail: z.string(),
  status: z.string(),
});
const listSchema = z.object({ rows: z.array(rowSchema) });

type Row = z.infer<typeof rowSchema>;
function statusClass(value: string) {
  const s = value.toLowerCase();
  if (/pass|ready|active|validated|complete/.test(s)) return "good";
  if (/fail|blocked|error|needs_fix/.test(s)) return "bad";
  if (/pending|review|qa|open/.test(s)) return "warn";
  return "neutral";
}

function Cards({ rows, kind }: { rows: Row[]; kind: string }) {
  if (!rows.length) return <div className="empty">No {kind.toLowerCase()} records in this snapshot.</div>;
  return (
    <div className="cards">
      {rows.map((item, index) => (
        <article className="data-card" key={index}>
          <div className="card-top"><strong>{item.title}</strong><span className={"state " + statusClass(item.status)}>{item.status}</span></div>
          <p>{item.detail}</p>
        </article>
      ))}
    </div>
  );
}

const ProjectPanel = defineComponent({
  name: "ProjectPanel",
  description: "Read-only mission cards; no links or actions",
  props: listSchema,
  component: ({ props }) => <Cards rows={props.rows} kind="project" />,
});
const AgentPanel = defineComponent({
  name: "AgentPanel",
  description: "Read-only worker/provider cards; no model launch actions",
  props: listSchema,
  component: ({ props }) => <Cards rows={props.rows} kind="agent" />,
});
const QaPanel = defineComponent({
  name: "QaPanel",
  description: "Read-only QA tasks and human-gate status; no gate resolution actions",
  props: listSchema,
  component: ({ props }) => (
    <>
      <div className="gate-notice">Human decisions are never submitted here. Resolve gates in the original Cockpit.</div>
      <Cards rows={props.rows} kind="QA" />
    </>
  ),
});
const CockpitScreen = defineComponent({
  name: "CockpitScreen",
  description: "Root screen with title, source label, and only registered read-only panels",
  props: z.object({
    title: z.string(),
    subtitle: z.string(),
    panels: z.array(z.any()),
  }),
  component: ({ props, renderNode }) => (
    <section className="generated-screen">
      <header className="generated-header">
        <div><p className="eyebrow">ADAPTIVE VIEW</p><h2>{props.title}</h2><p>{props.subtitle}</p></div>
        <span className="readonly">READ ONLY</span>
      </header>
      {renderNode(props.panels)}
    </section>
  ),
});

// Registry whitelist: model-supplied OpenUI Lang cannot introduce arbitrary HTML,
// Javascript, network tools, mutation actions or gate-approval controls.
export const library = createLibrary({
  id: "mcc-m2-9",
  root: "CockpitScreen",
  components: [CockpitScreen, ProjectPanel, AgentPanel, QaPanel],
});
