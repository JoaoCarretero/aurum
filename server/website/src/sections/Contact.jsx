import { useState } from "react";
import { Reveal } from "../components/Reveal";
import { SITE } from "../lib/data";
import { useT } from "../lib/i18n";

export function Contact() {
  const [state, setState] = useState({ name: "", email: "", org: "", note: "" });
  const [sent, setSent] = useState(false);
  const t = useT();

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
            <span className="section__num">{t("contact.eyebrow")}</span>
            <h2 className="section__title">
              {t("contact.titlePre")} <em>{t("contact.titleEm")}</em>
            </h2>
            <p className="section__sub">{t("contact.sub")}</p>
          </div>
        </Reveal>

        <Reveal delay={0.1}>
          <form className="contact-form" onSubmit={onSubmit}>
            <div className="contact-form__row">
              <label>
                <span>{t("contact.form.nameLabel")}</span>
                <input type="text" required {...bind("name")} placeholder={t("contact.form.namePh")} />
              </label>
              <label>
                <span>{t("contact.form.emailLabel")}</span>
                <input type="email" required {...bind("email")} placeholder={t("contact.form.emailPh")} />
              </label>
            </div>
            <label>
              <span>{t("contact.form.orgLabel")}</span>
              <input type="text" {...bind("org")} placeholder={t("contact.form.orgPh")} />
            </label>
            <label>
              <span>{t("contact.form.noteLabel")}</span>
              <textarea rows={4} {...bind("note")} placeholder={t("contact.form.notePh")} />
            </label>
            <div className="contact-form__foot">
              <button type="submit" className="btn btn--primary">
                {sent ? t("contact.form.sent") : t("contact.form.send")}
              </button>
              <span className="contact-form__note">
                {t("contact.form.or")} <a href={`mailto:${SITE.email}`}>{SITE.email}</a>
              </span>
            </div>
          </form>
        </Reveal>
      </div>
    </section>
  );
}
