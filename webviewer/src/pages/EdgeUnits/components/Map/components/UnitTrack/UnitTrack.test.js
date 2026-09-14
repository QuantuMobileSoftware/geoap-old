import { filterImagePoints, filterTrackByTimeRange, formatPointTime } from './UnitTrack';

jest.mock('lodash-es', () => require('lodash'));

const point = (overrides = {}) => ({
  t: '2026-08-26T12:00:00Z',
  lat: 49.8,
  lng: -98.3,
  img: false,
  det: 0,
  ...overrides
});

describe('filterImagePoints', () => {
  it('keeps only points that uploaded an image', () => {
    const track = [point({ img: true }), point({ img: false }), point({ img: true })];

    expect(filterImagePoints(track)).toEqual([track[0], track[2]]);
  });

  it('returns an empty array when no point carries an image', () => {
    const track = [point(), point()];

    expect(filterImagePoints(track)).toEqual([]);
  });
});

describe('formatPointTime', () => {
  const timezone = 'America/Regina';

  it('formats a valid timestamp in the account timezone', () => {
    expect(formatPointTime('2026-08-26T12:00:00Z', timezone)).toBe('06:00 CST');
  });

  it('falls back when t is null - a decimated point with no matched source row', () => {
    expect(formatPointTime(null, timezone)).toBe('unknown time');
  });
});

describe('filterTrackByTimeRange', () => {
  const track = [
    point({ t: '2026-08-26T11:00:00Z' }),
    point({ t: '2026-08-26T12:00:00Z' }),
    point({ t: '2026-08-26T13:00:00Z' }),
    point({ t: null })
  ];

  it('returns the full track unchanged when there is no selection', () => {
    expect(filterTrackByTimeRange(track, null)).toBe(track);
  });

  it('keeps only points inside the half-open [start, end) range', () => {
    const range = {
      start: new Date('2026-08-26T12:00:00Z').getTime(),
      end: new Date('2026-08-26T13:00:00Z').getTime()
    };

    expect(filterTrackByTimeRange(track, range)).toEqual([track[1]]);
  });

  it('drops points with a null t (decimated, no matched source row) once a selection is active', () => {
    const range = {
      start: new Date('2026-08-26T00:00:00Z').getTime(),
      end: new Date('2026-08-27T00:00:00Z').getTime()
    };

    expect(filterTrackByTimeRange(track, range)).toEqual([track[0], track[1], track[2]]);
  });
});
