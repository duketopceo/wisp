import { describe, expect, it } from 'vitest';
import { PROTOCOL, parseFromHost } from '../src/protocol';

describe('parseFromHost', () => {
  it('reads each message the host sends', () => {
    expect(parseFromHost({ t: 'hello_ok', v: PROTOCOL })).toEqual({ t: 'hello_ok', v: PROTOCOL });
    expect(parseFromHost({ t: 'pong' })).toEqual({ t: 'pong' });
    expect(parseFromHost({ t: 'error', code: 'bad_hello', message: 'no' })).toEqual({
      t: 'error',
      code: 'bad_hello',
      message: 'no',
    });
  });

  it('fills the defaults of an error with no fields', () => {
    expect(parseFromHost({ t: 'error' })).toEqual({ t: 'error', code: 'unknown', message: '' });
  });

  it('reads a batch command and defaults the task', () => {
    const m = parseFromHost({
      t: 'cmd',
      cmd: { id: 'c1', op: 'batch', steps: [{ do: 'open', url: 'http://a.test/' }] },
    });
    expect(m).toEqual({
      t: 'cmd',
      cmd: {
        id: 'c1',
        op: 'batch',
        task: 'task',
        steps: [{ do: 'open', url: 'http://a.test/' }],
        resume: false,
      },
    });
  });

  it('keeps resume only when it is exactly true', () => {
    const base = { id: 'c', op: 'batch', steps: [] };
    const get = (resume: unknown) => {
      const m = parseFromHost({ t: 'cmd', cmd: { ...base, resume } });
      return m && m.t === 'cmd' ? m.cmd.resume : undefined;
    };
    expect(get(true)).toBe(true);
    expect(get('true')).toBe(false);
    expect(get(1)).toBe(false);
  });

  it('reads an end_task command', () => {
    expect(parseFromHost({ t: 'cmd', cmd: { id: 'c2', op: 'end_task', task: 't1' } })).toEqual({
      t: 'cmd',
      cmd: { id: 'c2', op: 'end_task', task: 't1' },
    });
  });

  it.each([
    null,
    undefined,
    'text',
    7,
    [],
    {},
    { t: 'launch' },
    { t: 'hello_ok' },
    { t: 'hello_ok', v: '1' },
    { t: 'cmd' },
    { t: 'cmd', cmd: 'x' },
    { t: 'cmd', cmd: { op: 'batch', steps: [] } },
    { t: 'cmd', cmd: { id: '', op: 'batch', steps: [] } },
    { t: 'cmd', cmd: { id: 'c', op: 'run_js', steps: [] } },
    { t: 'cmd', cmd: { id: 'c', op: 'batch' } },
    { t: 'cmd', cmd: { id: 'c', op: 'batch', steps: ['open'] } },
  ])('drops %j', (raw) => {
    expect(parseFromHost(raw)).toBeNull();
  });
});
