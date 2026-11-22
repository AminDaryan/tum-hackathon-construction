import { afterEach, describe, expect, it, vi } from 'vitest';
import { fadeIn, fadeOut } from './motion.ts';

/** An element that records its animations; each one finishes when `finish` is called. */
function animatedElement() {
  const element = document.createElement('div');
  let finish = () => {};
  const animate = vi.fn(() => ({ finished: new Promise<void>((resolve) => (finish = resolve)) }));
  Object.defineProperty(element, 'animate', { value: animate });
  return { element, animate, finish: () => finish() };
}

describe('motion', () => {
  afterEach(() => {
    delete document.documentElement.dataset.motion;
  });

  it('fades new content in, unless motion is reduced', () => {
    const { element, animate } = animatedElement();
    fadeIn(element);
    expect(animate).toHaveBeenCalledWith([{ opacity: 0 }, { opacity: 1 }], expect.objectContaining({ duration: 150 }));

    document.documentElement.dataset.motion = 'reduce';
    fadeIn(element);
    expect(animate).toHaveBeenCalledTimes(1);
  });

  it('removes closing content once it has faded out, and at once with reduced motion', async () => {
    const { element, animate, finish } = animatedElement();
    const done = vi.fn();
    fadeOut(element, done);
    expect(animate).toHaveBeenCalledWith([{ opacity: 1 }, { opacity: 0 }], expect.objectContaining({ duration: 120, fill: 'forwards' }));
    expect(done).not.toHaveBeenCalled();
    finish();
    await vi.waitFor(() => expect(done).toHaveBeenCalledTimes(1));

    document.documentElement.dataset.motion = 'reduce';
    fadeOut(element, done);
    expect(done).toHaveBeenCalledTimes(2);
    expect(animate).toHaveBeenCalledTimes(1);
  });

  it('does nothing in a browser that cannot animate an element', () => {
    const done = vi.fn();
    expect(() => fadeIn(document.createElement('div'))).not.toThrow();
    fadeOut(document.createElement('div'), done);
    expect(done).toHaveBeenCalledTimes(1);
  });
});
