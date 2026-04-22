import { Nav } from "../components/Nav";
import { Footer } from "../components/Footer";
import { StatusTicker } from "../components/StatusTicker";
import { Hero } from "../sections/Hero";
import { Bento } from "../sections/Bento";
import { Thesis } from "../sections/Thesis";
import { Methodology } from "../sections/Methodology";
import { Performance } from "../sections/Performance";
import { CodeShowcase } from "../sections/CodeShowcase";
import { Technology } from "../sections/Technology";
import { Principles } from "../sections/Principles";
import { Research } from "../sections/Research";
import { Contact } from "../sections/Contact";

export function Landing() {
  return (
    <>
      <StatusTicker />
      <Nav />
      <main className="app">
        <Hero />
        <Bento />
        <Thesis />
        <Methodology />
        <Performance />
        <CodeShowcase />
        <Technology />
        <Principles />
        <Research />
        <Contact />
      </main>
      <Footer />
    </>
  );
}
