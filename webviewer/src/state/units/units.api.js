import { createApi } from '@reduxjs/toolkit/query/react';
import { axiosInstance } from 'api';

const axiosBaseQuery =
  () =>
  async ({ url, method = 'get', data, params, skipErrorModal }) => {
    try {
      const response = await axiosInstance({ url, method, data, params, skipErrorModal });
      return { data: response.data };
    } catch (error) {
      return { error: { status: error?.status ?? 'CUSTOM_ERROR', data: error } };
    }
  };

export const unitsApi = createApi({
  reducerPath: 'unitsApi',
  baseQuery: axiosBaseQuery(),
  endpoints: build => ({
    getUnits: build.query({
      query: () => ({ url: '/units' })
    }),
    getUnitsTelemetry: build.query({
      query: ({ day, rolling, unitId, rangeFrom, rangeTo } = {}) => ({
        url: '/units/telemetry',
        params: {
          day,
          rolling: rolling || undefined,
          unit_id: unitId,
          range_from: rangeFrom,
          range_to: rangeTo
        },
        // The rolling window can slide past a committed range while this request
        // is in flight.
        skipErrorModal: Boolean(rangeFrom || rangeTo)
      })
    }),
    getUnitLatestImageUrl: build.query({
      query: ({ unitId }) => ({
        url: `/units/${unitId}/latest_image_url/`,
        skipErrorModal: true
      })
    })
  })
});

export const {
  useGetUnitsQuery,
  useGetUnitsTelemetryQuery,
  useGetUnitLatestImageUrlQuery
} = unitsApi;
