// Playwright's onBegin/onEnd boundaries, alongside the outer command wall time.
import { mkdirSync, writeFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';

export default class TimingReporter {
  constructor() { this.loaded = performance.now(); }
  onBegin(config, suite) {
    this.begin = performance.now();
    this.count = suite.allTests().length;
  }
  onEnd(result) {
    const end = performance.now();
    mkdirSync('.artifacts/deps-experiment', { recursive: true });
    writeFileSync('.artifacts/deps-experiment/playwright-timing.json', JSON.stringify({
      reporter_load_to_onBegin_seconds: (this.begin - this.loaded) / 1000,
      onBegin_to_onEnd_seconds: (end - this.begin) / 1000,
      selected: this.count, status: result.status,
      note: 'onBegin to onEnd includes worker startup and hooks, not just individual test bodies; compare with tests.json outer wall time.'
    }, null, 2));
  }
}
