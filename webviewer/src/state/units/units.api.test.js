import MockAdapter from 'axios-mock-adapter';
import { configureStore } from '@reduxjs/toolkit';
import { axiosInstance } from 'api';
import { areasEvents } from '_events';
import { unitsApi } from './units.api';

jest.mock('_events', () => ({
  areasEvents: { toggleErrorModal: jest.fn() }
}));

const mock = new MockAdapter(axiosInstance);

const makeStore = () =>
  configureStore({
    reducer: { [unitsApi.reducerPath]: unitsApi.reducer },
    middleware: getDefaultMiddleware => getDefaultMiddleware().concat(unitsApi.middleware)
  });

afterEach(() => {
  mock.reset();
  jest.clearAllMocks();
});

describe('getUnitsTelemetry', () => {
  it('does not show the global error modal when a committed range is stale', async () => {
    mock.onGet('/units/telemetry').reply(400, {
      detail:
        "'range_from'/'range_to' must be a non-empty sub-range within the resolved window."
    });

    const store = makeStore();
    await store.dispatch(
      unitsApi.endpoints.getUnitsTelemetry.initiate({
        rolling: true,
        unitId: 'SS-0142',
        rangeFrom: '2026-08-26T12:00:00Z',
        rangeTo: '2026-08-26T12:15:00Z'
      })
    );

    expect(areasEvents.toggleErrorModal).not.toHaveBeenCalled();
  });

  it('still shows the global error modal for the plain (non-range) request', async () => {
    mock.onGet('/units/telemetry').reply(500, { detail: 'Internal Server Error' });

    const store = makeStore();
    await store.dispatch(
      unitsApi.endpoints.getUnitsTelemetry.initiate({ rolling: true })
    );

    expect(areasEvents.toggleErrorModal).toHaveBeenCalledTimes(1);
  });
});

describe('getUnitLatestImageUrl', () => {
  it('does not show the global error modal when the unit has no image yet', async () => {
    mock
      .onGet('/units/SS-0142/latest_image_url/')
      .reply(404, { detail: 'No image has been received for this unit yet.' });

    const store = makeStore();
    await store.dispatch(
      unitsApi.endpoints.getUnitLatestImageUrl.initiate({ unitId: 'SS-0142' })
    );

    expect(areasEvents.toggleErrorModal).not.toHaveBeenCalled();
  });

  it('does not show the global error modal on a storage error either', async () => {
    mock.onGet('/units/SS-0142/latest_image_url/').reply(400, {
      detail:
        'Storage bucket is not available. Please check the bucket name in your account settings.'
    });

    const store = makeStore();
    await store.dispatch(
      unitsApi.endpoints.getUnitLatestImageUrl.initiate({ unitId: 'SS-0142' })
    );

    expect(areasEvents.toggleErrorModal).not.toHaveBeenCalled();
  });

  it('surfaces the 404 as a plain message, not a distinguishable status', async () => {
    mock
      .onGet('/units/SS-0142/latest_image_url/')
      .reply(404, { detail: 'No image has been received for this unit yet.' });

    const store = makeStore();
    const result = await store.dispatch(
      unitsApi.endpoints.getUnitLatestImageUrl.initiate({ unitId: 'SS-0142' })
    );

    // The shared axios interceptor unwraps `.detail` into a plain string,
    // dropping the HTTP status - so this is 'CUSTOM_ERROR', never 404.
    expect(result.error).toEqual({
      status: 'CUSTOM_ERROR',
      data: 'No image has been received for this unit yet.'
    });
  });
});
