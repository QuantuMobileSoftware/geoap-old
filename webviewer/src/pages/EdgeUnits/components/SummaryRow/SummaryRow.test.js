import { summaryFields } from './SummaryRow';

jest.mock('lodash-es', () => require('lodash'));

const totals = (overrides = {}) => ({
  messages: 12,
  distance_km: 4.567,
  images: 3,
  detections: 5,
  first_at: '2026-08-26T12:00:00Z',
  last_at: '2026-08-26T13:30:00Z',
  gap_minutes: 0,
  ...overrides
});

describe('summaryFields', () => {
  const timezone = 'America/Regina';

  it('formats all six stats when there is data', () => {
    const fields = summaryFields(totals({ gap_minutes: 45 }), timezone);

    expect(fields).toEqual({
      messages: '12',
      distance: '4.6 km',
      firstMessage: '06:00 CST',
      lastMessage: '07:30 CST',
      images: '3',
      detections: '5',
      quietTime: '45 min'
    });
  });

  it('shows "none" for quiet time when there were no gaps, not "0 min"', () => {
    expect(summaryFields(totals({ gap_minutes: 0 }), timezone).quietTime).toBe('none');
  });

  it('shows dashes for every field when there are zero messages in the window', () => {
    const fields = summaryFields(totals({ messages: 0 }), timezone);

    expect(Object.values(fields).every(value => value === '—')).toBe(true);
  });

  it('shows dashes for every field when totals is missing entirely (no selection fetched yet, or empty)', () => {
    const fields = summaryFields(undefined, timezone);

    expect(Object.values(fields).every(value => value === '—')).toBe(true);
  });
});
