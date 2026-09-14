import styled, { css } from 'styled-components';
import { em, rem } from 'styles';

export const Row = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: ${em(16)};
  margin-top: ${em(10)};
`;

export const Stat = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${em(2)};
`;

export const StatLabel = styled.span`
  ${({ theme }) => css`
    font-family: ${theme.fonts.mono};
    font-size: ${rem(10)};
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: ${theme.colors.nature.n4};
  `}
`;

export const StatValue = styled.span`
  ${({ theme }) => css`
    font-family: ${theme.fonts.mono};
    font-size: ${rem(13)};
    color: ${theme.colors.nature.n5};
  `}
`;
