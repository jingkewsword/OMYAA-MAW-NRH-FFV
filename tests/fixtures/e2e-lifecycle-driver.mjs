import { startScrollFixture } from '../e2e/cue-scroll-fixture.mjs';

const server = await startScrollFixture({ count: 1 });
await server.stop();
await server.stop();
console.log(JSON.stringify({ directory: server.directory, url: server.url }));
process.send?.({ stopped: true });
