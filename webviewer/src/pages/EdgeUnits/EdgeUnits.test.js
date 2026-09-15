import { hasNoUnits } from './EdgeUnits';

jest.mock('lodash-es', () => require('lodash'));

describe('hasNoUnits', () => {
  it('is true once units have loaded and the account has none', () => {
    expect(hasNoUnits({ units: [] }, false, false)).toBe(true);
  });

  it('is false while units are still loading', () => {
    expect(hasNoUnits(undefined, true, false)).toBe(false);
  });

  it('is false on a load error (that gets the normal retry UI instead)', () => {
    expect(hasNoUnits(undefined, false, true)).toBe(false);
  });

  it('is false once the account has at least one unit', () => {
    expect(hasNoUnits({ units: [{ unit_id: 'SS-0142' }] }, false, false)).toBe(false);
  });
});
