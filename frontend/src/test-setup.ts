import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";

beforeEach(() => {
  delete document.documentElement.dataset.siteHostname;
});

afterEach(() => {
  delete document.documentElement.dataset.siteHostname;
});
