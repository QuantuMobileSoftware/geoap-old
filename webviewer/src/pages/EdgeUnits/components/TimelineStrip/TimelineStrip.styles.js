import styled, { css } from 'styled-components';
import { em, rem } from 'styles';

export const Wrapper = styled.div`
  display: flex;
  flex-direction: column;
  width: 100%;
`;

const BAR_COLOR_HEIGHT = {
  ok: css`
    ${({ theme }) => css`
      background: ${theme.colors.status.live};
      height: 100%;
    `}
  `,
  thin: css`
    ${({ theme }) => css`
      background: ${theme.colors.status.late};
      height: 58%;
    `}
  `,
  gap: css`
    ${({ theme }) => css`
      background: ${theme.colors.status.silent};
      height: 20%;
    `}
  `
};

const BASE_OPACITY = { ok: 1, thin: 1, gap: 0.3 };
const OUT_OF_SELECTION_FACTOR = 0.2;

export const Bars = styled.div`
  ${({ theme }) => css`
    display: flex;
    align-items: flex-end;
    gap: ${em(1)};
    height: ${em(52)};
    padding: ${em(1)};
    background: ${theme.colors.nature.n1};
    border-radius: ${theme.radius[0]}px;
    cursor: ew-resize;
    touch-action: none;
    user-select: none;
  `}
`;

export const Bar = styled.div`
  flex: 1;
  min-width: 1px;
  border-radius: 1px;
  ${({ $state }) => BAR_COLOR_HEIGHT[$state]}
  opacity: ${({ $state, $isOutside }) =>
    BASE_OPACITY[$state] * ($isOutside ? OUT_OF_SELECTION_FACTOR : 1)};
`;

export const Axis = styled.div`
  ${({ theme }) => css`
    display: flex;
    justify-content: space-between;
    margin-top: ${em(4)};
    font-family: ${theme.fonts.mono};
    font-size: ${rem(9.5)};
    letter-spacing: 0.05em;
    color: ${theme.colors.nature.n3};
  `}
`;

export const AxisLabel = styled.span``;

export const Controls = styled.div`
  display: flex;
  justify-content: flex-end;
  margin-top: ${em(6)};
`;

export const RangeSelect = styled.select`
  ${({ theme }) => css`
    font-family: ${theme.fonts.mono};
    font-size: ${rem(11)};
    padding: ${em(3)} ${em(6)};
    background: ${theme.colors.nature.n0};
    color: ${theme.colors.nature.n4};
    border: ${em(1)} solid ${theme.colors.nature.n2};
    border-radius: ${theme.radius[0]}px;
  `}
`;
