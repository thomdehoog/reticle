import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

/**
 * The rules here are the ones that catch bugs TypeScript cannot see.
 *
 * `tsc --noEmit` already runs in CI and proves the types line up. What it
 * cannot tell you is that an effect reads a value it never declared, which is
 * how a component ends up rendering last request's data — the type of the stale
 * variable is perfectly correct. `react-hooks` is therefore the reason this
 * file exists, and its rules are errors rather than warnings.
 *
 * Deliberately not included: stylistic rules. Formatting arguments in review
 * are a tax, and nothing here is a defect.
 */
export default tseslint.config(
  { ignores: ['dist', 'coverage', 'e2e/shots'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      // An unused variable is usually a rename that was only half applied, or a
      // prop somebody stopped passing. The underscore escape is for the genuine
      // cases: a callback signature that hands you an argument you do not want.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],

      // `any` switches off the checker for everything downstream of it, which
      // is exactly where a wrong shape survives to runtime. A warning rather
      // than an error: the boundary where untyped JSON arrives is a legitimate
      // place for one, and it should be visible rather than forbidden.
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
  {
    // Tests reach into internals on purpose, and a test that throws is often
    // the assertion itself.
    files: ['**/*.test.{ts,tsx}', 'e2e/**/*.mjs'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      // The adversarial tests feed control characters in on purpose — that is
      // the input being defended against. Forbidding them here would forbid
      // testing for them.
      'no-control-regex': 'off',
    },
  },
)
