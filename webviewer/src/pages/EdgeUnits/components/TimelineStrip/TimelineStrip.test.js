import { formatInTimezone } from 'utils';
import {
  axisLabels,
  bucketBarState,
  bucketRangeToTimeRange,
  dropdownRange,
  isBucketOutsideSelection,
  isTimeRangeWithinWindow,
  selectionForDrag,
  selectionOnRelease
} from './TimelineStrip';

jest.mock('lodash-es', () => require('lodash'));

describe('bucketBarState', () => {
  it('maps 0 to a gap', () => {
    expect(bucketBarState(0)).toBe('gap');
  });

  it('maps 1 to partial coverage', () => {
    expect(bucketBarState(1)).toBe('thin');
  });

  it('maps 2 (and anything above) to full coverage', () => {
    expect(bucketBarState(2)).toBe('ok');
    expect(bucketBarState(3)).toBe('ok');
  });
});

describe('axisLabels', () => {
  it('returns the fixed relative-hour labels in rolling mode, ignoring from/to', () => {
    const labels = axisLabels({
      rolling: true,
      from: null,
      to: null,
      timezone: 'America/Regina'
    });

    expect(labels).toEqual(['−24 h', '−18', '−12', '−6', 'now']);
  });

  it('returns nothing when from/to/timezone are not resolved yet', () => {
    expect(axisLabels({ rolling: false, from: null, to: null, timezone: null })).toEqual(
      []
    );
  });

  it('spaces 5 ticks across a normal 24h day, start and end on the same wall clock time', () => {
    const labels = axisLabels({
      rolling: false,
      from: '2026-08-26T05:00:00Z',
      to: '2026-08-27T05:00:00Z',
      timezone: 'America/Regina'
    });

    expect(labels).toHaveLength(5);
    expect(labels[0]).toBe(labels[4]);
    expect(labels[2]).not.toBe(labels[0]);
  });

  // Regression guard for the bug this function exists to avoid: ticks must
  // come from the real from/to duration, not from quartering buckets.length
  // (92/100 on DST-boundary days) - otherwise the first and last labels
  // would drift off local midnight on exactly these two days.
  it('still lands start and end on the same wall clock time on a 23h spring-forward day', () => {
    const labels = axisLabels({
      rolling: false,
      from: '2026-03-08T06:00:00Z',
      to: '2026-03-09T05:00:00Z', // 23h window
      timezone: 'America/Winnipeg'
    });

    expect(labels).toHaveLength(5);
    expect(labels[0]).toBe(labels[4]);
  });

  it('still lands start and end on the same wall clock time on a 25h fall-back day', () => {
    const labels = axisLabels({
      rolling: false,
      from: '2026-11-01T05:00:00Z',
      to: '2026-11-02T06:00:00Z', // 25h window
      timezone: 'America/Winnipeg'
    });

    expect(labels).toHaveLength(5);
    expect(labels[0]).toBe(labels[4]);
  });
});

describe('selectionForDrag', () => {
  it('orders start/end regardless of drag direction', () => {
    expect(selectionForDrag(10, 20)).toEqual({ start: 10, end: 20 });
    expect(selectionForDrag(20, 10)).toEqual({ start: 10, end: 20 });
  });

  it('returns null when either index is missing', () => {
    expect(selectionForDrag(null, 5)).toBeNull();
    expect(selectionForDrag(5, null)).toBeNull();
  });
});

describe('selectionOnRelease', () => {
  it('keeps a real range', () => {
    expect(selectionOnRelease({ start: 3, end: 8 })).toEqual({ start: 3, end: 8 });
  });

  it('clears a range that never moved off its anchor - a click, not a drag', () => {
    expect(selectionOnRelease({ start: 5, end: 5 })).toBeNull();
  });

  it('stays null when there was no drag at all', () => {
    expect(selectionOnRelease(null)).toBeNull();
  });
});

describe('isBucketOutsideSelection', () => {
  const range = { start: 10, end: 20 };

  it('is false with no selection', () => {
    expect(isBucketOutsideSelection(5, null)).toBe(false);
  });

  it('is false inside the range, including both edges', () => {
    expect(isBucketOutsideSelection(10, range)).toBe(false);
    expect(isBucketOutsideSelection(20, range)).toBe(false);
    expect(isBucketOutsideSelection(15, range)).toBe(false);
  });

  it('is true outside the range', () => {
    expect(isBucketOutsideSelection(9, range)).toBe(true);
    expect(isBucketOutsideSelection(21, range)).toBe(true);
  });
});

describe('bucketRangeToTimeRange', () => {
  const context = { from: '2026-09-14T06:00:00Z', bucketMinutes: 15 };

  it('converts a bucket range to a half-open time range', () => {
    expect(bucketRangeToTimeRange({ start: 24, end: 47 }, context)).toEqual({
      start: new Date('2026-09-14T12:00:00Z').getTime(),
      end: new Date('2026-09-14T18:00:00Z').getTime()
    });
  });

  it('returns null with no selection', () => {
    expect(bucketRangeToTimeRange(null, context)).toBeNull();
  });
});

describe('dropdownRange', () => {
  // Local midnight America/Regina (UTC-6, no DST) is 06:00Z - a clean 96-bucket day.
  const normalDay = {
    from: '2026-09-14T06:00:00Z',
    bucketMinutes: 15,
    bucketCount: 96,
    timezone: 'America/Regina',
    rolling: false
  };

  it('matches the prototype fixed quarters on a normal 96-bucket day', () => {
    expect(dropdownRange('morning', normalDay)).toEqual({ start: 24, end: 47 });
    expect(dropdownRange('afternoon', normalDay)).toEqual({ start: 48, end: 71 });
    expect(dropdownRange('evening', normalDay)).toEqual({ start: 72, end: 95 });
  });

  it('agrees with a drag over the same logical range - the two paths must produce identical state', () => {
    expect(dropdownRange('morning', normalDay)).toEqual(selectionForDrag(24, 47));
  });

  it('clears to the full window ("whole-day")', () => {
    expect(dropdownRange('whole-day', normalDay)).toBeNull();
  });

  it('is disabled (null) in rolling mode, where morning/afternoon/evening are ambiguous', () => {
    expect(dropdownRange('morning', { ...normalDay, rolling: true })).toBeNull();
  });

  // Regression guard: naive hour*60/bucketMinutes arithmetic silently drifts
  // by a whole bucket-block on the two days a year an hour is skipped/repeated.
  it('finds the real DST-adjusted bucket for a clock hour, not naive hour*4 arithmetic', () => {
    const springForward = {
      from: '2026-03-08T06:00:00Z',
      bucketMinutes: 15,
      bucketCount: 92,
      timezone: 'America/Winnipeg',
      rolling: false
    };

    const range = dropdownRange('morning', springForward);
    expect(range).not.toBeNull();

    const bucketInstant = new Date(
      new Date(springForward.from).getTime() +
        range.start * springForward.bucketMinutes * 60000
    );
    const localHour = formatInTimezone(bucketInstant, springForward.timezone, {
      hour: '2-digit',
      hour12: false
    });

    expect(Number(localHour)).toBe(6);
    expect(range.start).not.toBe(24); // what naive hour*4 arithmetic would have said
  });
});

describe('isTimeRangeWithinWindow', () => {
  it('accepts a range fully inside the window, including touching both edges', () => {
    const windowFrom = '2026-09-14T06:00:00Z';
    const windowTo = '2026-09-15T06:00:00Z';
    const range = {
      start: new Date(windowFrom).getTime(),
      end: new Date(windowTo).getTime()
    };

    expect(isTimeRangeWithinWindow(range, windowFrom, windowTo)).toBe(true);
  });

  // a committed selection made
  // against one window (e.g. before a rolling-mode poll, or before a
  // day/rolling switch) re-derived against a *new* from/to before the reset
  // effect has cleared it - must be rejected, not sent to the backend.
  it('rejects a range from a window that no longer exists (stale selection re-applied to a new window)', () => {
    const oldWindowFrom = '2026-09-13T06:00:00Z';
    const range = {
      start: new Date(oldWindowFrom).getTime() + 80 * 15 * 60000,
      end: new Date(oldWindowFrom).getTime() + 91 * 15 * 60000
    };
    const newWindowFrom = '2026-09-14T06:00:00Z'; // a whole day later
    const newWindowTo = '2026-09-15T06:00:00Z';

    expect(isTimeRangeWithinWindow(range, newWindowFrom, newWindowTo)).toBe(false);
  });

  it('rejects when there is no range, or the window is not resolved yet', () => {
    expect(
      isTimeRangeWithinWindow(null, '2026-09-14T06:00:00Z', '2026-09-15T06:00:00Z')
    ).toBe(false);
    expect(isTimeRangeWithinWindow({ start: 0, end: 1 }, null, null)).toBe(false);
  });
});
