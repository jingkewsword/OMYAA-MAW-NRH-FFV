import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:net';
import { cleanupTempDir, findFreePort, generateWav, generateWaveformPayload, makeTempDir } from './e2e/helpers.mjs';
import { spawnServerProcess, stopServerProcess } from './e2e/server-process.mjs';

async function requireFreePort(port) {
  const deadline=Date.now()+2000;
  for(;;) {
    const listener=createServer();
    try {
      await new Promise((resolve,reject)=>{listener.once('error',reject);listener.listen(port,'127.0.0.1',resolve);});
      await new Promise(resolve=>listener.close(resolve));
      return;
    } catch(error) {
      if(error.code!=='EADDRINUSE'||Date.now()>=deadline)throw error;
      await new Promise(resolve=>setTimeout(resolve,25));
    }
  }
}

for(const crash of [false,true]) {
  test(`Launcher thumbnail fixture releases its real Server port after ${crash?'abrupt fixture exit':'owner group teardown'}`,
    {timeout:45000},async()=>{
      const root=makeTempDir('launcher-thumbnail-lifecycle'),app=join(root,'.settings');
      mkdirSync(app,{recursive:true});
      const media=join(root,'audio.wav'),project=join(root,'project.mosp'),port=await findFreePort();
      generateWav(media,2);
      writeFileSync(project,JSON.stringify({media,waveform:generateWaveformPayload(2000),segments:[]}));
      const configured=process.env.MAW_E2E_PYTHON;
      const args=[...(configured?[]:['run','--frozen','python']),
        'tests/e2e/fixtures/launcher-thumbnail-server.py',project,String(port),...(crash?['--exit-after-start']:[])];
      const proc=spawnServerProcess(configured||'uv',args,{cwd:process.cwd(),env:{...process.env,
        MAW_APP_DATA_ROOT:app,LOCALAPPDATA:app,XDG_CONFIG_HOME:app}});
      const evidenceDir=process.env.MAW_EBUSY_EVIDENCE_DIR || '.artifacts/ebusy-diagnostic';
      mkdirSync(evidenceDir,{recursive:true});
      const evidencePath=join(evidenceDir,crash?'abrupt.json':'owner.json');
      const evidence={case:crash?'abrupt':'owner',root,media,port,events:[]};
      const observe=(event,data={})=>{evidence.events.push({event,time:new Date().toISOString(),...data});writeFileSync(evidencePath,JSON.stringify(evidence,null,2));};
      const diagnostic=(mode,...values)=>{
        if(process.platform!=='win32')return {status:'not_windows'};
        try {return JSON.parse(execFileSync(configured||'python',['tests/e2e/fixtures/windows_ebusy_observe.py',mode,...values.map(String)],{encoding:'utf8'}));}
        catch(error) {return {status:'query_failed',error:String(error)};}
      };
      let output='',stderr='',serverPid,fixturePid,fixtureProcesses,mainError,cleanupError;
      observe('supervisor_spawn',{pid:proc.pid,processes:diagnostic('processes',proc.pid)});
      proc.once('close',(code,signal)=>observe('supervisor_close',{code,signal}));
      proc.stderr.on('data',chunk=>{stderr=(stderr+chunk.toString()).slice(-4000);});
      const closed=new Promise((resolve,reject)=>{proc.once('close',resolve);proc.once('error',reject);});
      void closed.catch(()=>{});
      let timer;
      try {
        await new Promise((resolve,reject)=>{
          timer=setTimeout(()=>reject(new Error(`fixture startup deadline: ${stderr}`)),30000);
          proc.stdout.on('data',chunk=>{
            output+=chunk.toString();
            if(output.split('\n').some(line=>{
              try {
                const result=JSON.parse(line);
                if(result.ok===true){serverPid=result.fixtureServerPid;fixturePid=result.fixturePid;fixtureProcesses=result.diagnosticProcesses;return true;}
                return false;
              } catch{return false;}
            }))resolve();
          });
          proc.once('error',reject);
          proc.once('close',()=>{
            if(!output.includes('"ok": true'))reject(new Error(`fixture exited before startup: ${stderr}`));
          });
        });
        clearTimeout(timer);
        observe('fixture_ready',{supervisorPid:proc.pid,fixturePid,serverPid,processes:fixtureProcesses});
        observe('stop_start');
        if(crash)assert.equal(await closed,71,stderr);
        else await stopServerProcess(proc);
        observe('stop_complete');
        try { await requireFreePort(port); observe('port_bind',{result:'success'}); }
        catch(error) { observe('port_bind',{result:'failed',error:String(error)}); throw error; }
      } catch(error) {
        mainError=error;
        observe('main_error',{error:String(error),stack:error.stack});
      } finally {
        clearTimeout(timer);
        try { await stopServerProcess(proc); } catch(error) { cleanupError=error; observe('cleanup_stop_error',{error:String(error),stack:error.stack}); }
        // A failing regression must not itself leave the formerly escaped group.
        // Only use the PID reported by this test-owned Launcher fixture.
        if(process.platform!=='win32'&&Number.isInteger(serverPid)) {
          try {process.kill(-serverPid,'SIGKILL');}
          catch(error) {if(error.code!=='ESRCH')throw error;}
        }
        try { cleanupTempDir(root); observe('first_delete',{result:'success'});
          observe('post_delete_processes',{processes:diagnostic('processes',proc.pid,fixturePid || 0,serverPid || 0)}); }
        catch(error) {
          // Query immediately after the first failure; no retry or delay.
          const locks=error.code==='EBUSY' ? diagnostic('locks',media) : null;
          observe('first_delete',{result:'failed',code:error.code,error:String(error),locks,
            processes:diagnostic('processes',proc.pid,fixturePid || 0,serverPid || 0)});
          cleanupError=cleanupError ? new AggregateError([cleanupError,error],'multiple cleanup failures') : error;
        }
      }
      if(mainError && cleanupError) throw new AggregateError([mainError,cleanupError],'test and cleanup failed');
      if(mainError) throw mainError;
      if(cleanupError) throw cleanupError;
    });
}
