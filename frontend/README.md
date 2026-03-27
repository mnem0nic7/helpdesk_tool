# Frontend

React 19 + Vite SPA for the Altlassian operations portal.

This frontend serves multiple product surfaces from one codebase:

- Primary OIT helpdesk dashboard
- OasisDev helpdesk scope
- Azure Control Center

Routing switches at runtime based on site branding in `src/lib/siteContext.ts` and `src/App.tsx`.

## Stack

- React 19
- React Router 7
- React Query 5
- Tailwind CSS 4
- Recharts 3
- Vitest + Testing Library

## Commands

From `frontend/`:

```bash
npm run dev
npm run build
npm run test:run
npm test
npm run lint
```

## Local development

- Vite runs on `http://localhost:5173`
- `/api` requests proxy to `http://localhost:8000`
- The backend must be running for most page flows to work

The simplest full-stack local workflow from the repo root is:

```bash
./start.sh
```

## Structure

- `src/App.tsx`: top-level route selection for helpdesk vs Azure surfaces
- `src/components/`: shared layout, tables, forms, charts, and reusable UI
- `src/pages/`: page-level route components
- `src/lib/api.ts`: typed API client and response models
- `src/__tests__/`: page and component tests

## Testing guidance

- Use `npm run test:run` for CI-style execution
- Use `npm test` for watch mode while iterating
- Add or update tests when changing API contracts, route behavior, filters, or chart-driven interactions

## Build notes

- `npm run build` performs the TypeScript project build and the Vite production bundle
- Vendor chunking is customized in `vite.config.ts` for router, React Query, React Table, and Recharts dependencies

## Reports page notes

- `src/pages/ReportsPage.tsx` owns the report builder, saved templates, preview table, AI summary display, and export actions.
- The preview section includes an `Export Current View` button that exports the currently selected columns, active filters, sort, and grouping by reusing the same report export API as the page-level export action.
