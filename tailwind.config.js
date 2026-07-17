module.exports = {
  darkMode: ["class"],
  content: [],
  safelist: [
    'bg-red-50', 'text-red-800', 'border-red-200',
    'bg-yellow-50', 'text-yellow-800', 'border-yellow-200',
    'bg-green-50', 'text-green-800', 'border-green-200',
    'bg-blue-50', 'text-blue-800', 'border-blue-200',
    'bg-gray-50', 'text-gray-800', 'border-gray-200',
  ],
  theme: {
    extend: {
      aspectRatio: {
        '3/2': '3 / 2',
      },
    },
    container: {
      center: true,
    },
  },
  variants: {
    extend: {},
  },
  plugins: [],
}
