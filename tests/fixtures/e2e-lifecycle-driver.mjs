import { startScrollFixture } from '../e2e/cue-scroll-fixture.mjs';
import { startServer, findFreePort } from '../e2e/helpers.mjs';
import { writeFileSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const [kind = 'scroll', action = 'stop', deadline] = process.argv.slice(2);
// Only this synthetic driver opts into short deadlines. Actual app fixtures
// retain their generous defaults, including the Windows Job Object startup.
const readinessTimeoutMs = Number(deadline);
let server;
try {
  if (kind === 'scroll') server = await startScrollFixture({ count: 1, readinessTimeoutMs });
  else {
    const directory = join(process.env.MAW_SCROLL_EVIDENCE, 'helper');
    mkdirSync(directory, { recursive: true });
    const port = await findFreePort();
    writeFileSync(join(directory, 'runtime.json'), JSON.stringify({ port }));
    server = await startServer(join(directory, 'synthetic.json'), join(directory, 'synthetic.wav'), port, { readinessTimeoutMs });
  }
} catch (error) {
  process.send?.({ failure: error.message });
  process.disconnect?.();
  process.exitCode = 1;
}
if (server) {
  if (action === 'exit') process.exit(0);
  else if (action === 'exception') throw new Error('synthetic unhandled exception');
  else if (action.startsWith('signal:')) process.emit(action.slice(7));
  else if (action === 'hold') {
    // startServer has observed a real HTTP response. Capture the evidence at
    // that instant, before the parent test kills this owner.
    const directory = join(process.env.MAW_SCROLL_EVIDENCE, readdirSync(process.env.MAW_SCROLL_EVIDENCE)[0]);
    const pids = JSON.parse(readFileSync(join(directory, 'owned-pids.json')));
    process.send?.({ ready: true, pids });
  }
  else {
    await Promise.all([server.stop(), server.stop()]);
    await server.stop();
    process.send?.({ stopped: true });
    process.disconnect?.();
  }
}
