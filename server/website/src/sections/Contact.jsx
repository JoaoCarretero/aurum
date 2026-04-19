import { useState } from "react";
import { Reveal } from "../components/Reveal";
import { SITE } from "../lib/data";

export function Contact() {
  const [state, setState] = useState({ name: "", email: "", org: "", note: "" });
  const [sent, setSent] = useState(false);

  function onSubmit(e) {
    e.preventDefault();
    // Frontend-only for now. Compose a mailto: so the request lands
    // cleanly without a backend dependency.
    const subject = encodeURIComponent(`[AURUM] Research access · ${state.name || "anon"}`);
    const body = encodeURIComponent(
      `Name: ${state.name}\nEmail: ${state.email}\nOrganisation: ${state.org}\n\n${state.note}`
    );
    window.location.href = `mailto:${SITE.email}?subject=${subject}&body=${body}`;
    setSent(true);
  }

  function bind(field) {
    return {
      value: state[field],
      onChange: (e) => setState((s) => ({ ...s, [field]: e.target.value })),
    };
  }

  return (
    <section id="contact" className="section section--contact">
      <div className="section__inner">
        <Reveal>
          <div className="section__head section__head--center">
            <span className="section__num">§ IX</span>
            <h2 className="section__title">
              Invitation only. Limited <em>capacity.</em>
            </h2>
            <p className="section__sub">
              AURUM allocates under a strategy-capacity constraint, not a
              demand constraint. Reach out for research access or to
              discuss allocation under NDA.
            </p>
          </div>
        </Reveal>

        <Reveal delay={0.1}>
          <form className="contact-form" onSubmit={onSubmit}>
            <div className="contact-form__row">
              <label>
                <span>Name</span>
                <input type="text" required {...bind("name")} placeholder="Jane Investor" />
              </label>
              <label>
                <span>Email</span>
                <input type="email" required {...bind("email")} placeholder="jane@family-office.com" />
              </label>
            </div>
            <label>
              <span>Organisation</span>
              <input type="text" {...bind("org")} placeholder="Optional" />
            </label>
            <label>
              <span>Context</span>
              <textarea
                rows={4}
                {...bind("note")}
                placeholder="What would you like to discuss — research notes, allocation timeline, technical diligence?"
              />
            </label>
            <div className="contact-form__foot">
              <button type="submit" className="btn btn--primary">
                {sent ? "Opened your mail client" : "Send request"}
              </button>
              <span className="contact-form__note">
                Or write directly to <a href={`mailto:${SITE.email}`}>{SITE.email}</a>
              </span>
            </div>
          </form>
        </Reveal>
      </div>
    </section>
  );
}
