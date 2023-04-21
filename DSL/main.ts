import process from 'process';

process.argv.forEach((val, index) => {
    console.log(`${index}: ${val}`);
    console.log(process.argv.length)
  });