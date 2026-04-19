import { Nav } from "./components/Nav";
import { Footer } from "./components/Footer";
import { Hero } from "./sections/Hero";
import { Thesis } from "./sections/Thesis";
import { Methodology } from "./sections/Methodology";
import { Performance } from "./sections/Performance";
import { Technology } from "./sections/Technology";
import { Principles } from "./sections/Principles";
import { Research } from "./sections/Research";
import { Contact } from "./sections/Contact";

export default function App() {
  return (
    <>
      <Nav />
      <main className="app">
        <Hero />
        <Thesis />
        <Methodology />
        <Performance />
        <Technology />
        <Principles />
        <Research />
        <Contact />
      </main>
      <Footer />
    </>
  );
}
