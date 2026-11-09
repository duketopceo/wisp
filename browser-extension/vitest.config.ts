import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
    environment: 'node',
    // fixed order, no shared state: runs are repeatable
    sequence: { shuffle: false },
    restoreMocks: true,
  },
});
