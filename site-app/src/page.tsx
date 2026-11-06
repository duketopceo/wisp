// Rendered once at build time by build.mjs; the browser receives static HTML.
import { renderToStaticMarkup } from "react-dom/server";

import { CostCard, Faq, Features, Footer, Hero, Install, Navbar, Steps, Trust } from "./components/sections/sections";

function Page() {
  return (
    <>
      <Navbar />
      <main id="main">
        <Hero />
        <Features />
        <Steps />
        <Install />
        <Trust />
        <CostCard />
        <Faq />
      </main>
      <Footer />
    </>
  );
}

export function render(): string {
  return renderToStaticMarkup(<Page />);
}
