import { getMapEmptyMessage, shouldRefit } from './Map';

jest.mock('lodash-es', () => require('lodash'));

describe('getMapEmptyMessage', () => {
  it('returns null when at least one visible unit has track data', () => {
    const message = getMapEmptyMessage({
      unitCount: 3,
      unitsWithTrackCount: 1,
      rolling: true,
      resolvedDay: '2026-08-26'
    });

    expect(message).toBeNull();
  });

  it('blames the filter when the chip filter matched zero units', () => {
    const message = getMapEmptyMessage({
      unitCount: 0,
      unitsWithTrackCount: 0,
      rolling: true,
      resolvedDay: '2026-08-26'
    });

    expect(message).toBe('No units match this filter.');
  });

  it('reports the rolling window as empty when units exist but none have track data', () => {
    const message = getMapEmptyMessage({
      unitCount: 3,
      unitsWithTrackCount: 0,
      rolling: true,
      resolvedDay: '2026-08-26'
    });

    expect(message).toBe(
      'No telemetry in the last 24 hours. The units may be powered off.'
    );
  });

  it('names the selected day when a specific (non-rolling) day is empty', () => {
    const message = getMapEmptyMessage({
      unitCount: 3,
      unitsWithTrackCount: 0,
      rolling: false,
      resolvedDay: '2026-08-26'
    });

    expect(message).toContain('Nothing recorded on');
  });

  it('prioritizes the filter message even when the window is also empty', () => {
    const message = getMapEmptyMessage({
      unitCount: 0,
      unitsWithTrackCount: 0,
      rolling: false,
      resolvedDay: '2026-08-26'
    });

    expect(message).toBe('No units match this filter.');
  });
});

describe('shouldRefit', () => {
  const lastFit = { dayKey: '2026-08-26|false', manualFitCount: 0 };

  it('does not refit while the new day/window has no points yet', () => {
    expect(
      shouldRefit({ points: [], dayKey: '2026-08-27|false', manualFitCount: 0, lastFit })
    ).toBe(false);
  });

  it('refits once points arrive for a day it has not fit yet', () => {
    expect(
      shouldRefit({
        points: [[49.8, -98.3]],
        dayKey: '2026-08-27|false',
        manualFitCount: 0,
        lastFit
      })
    ).toBe(true);
  });

  it('does not refit again for the same day on a poll refresh', () => {
    expect(
      shouldRefit({
        points: [[49.8, -98.3]],
        dayKey: lastFit.dayKey,
        manualFitCount: lastFit.manualFitCount,
        lastFit
      })
    ).toBe(false);
  });

  it('refits on a manual Fit track click even on the same day', () => {
    expect(
      shouldRefit({
        points: [[49.8, -98.3]],
        dayKey: lastFit.dayKey,
        manualFitCount: lastFit.manualFitCount + 1,
        lastFit
      })
    ).toBe(true);
  });
});
