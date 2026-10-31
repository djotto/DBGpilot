// Keep the live scenario suite and the compatibility smoke suite on one matrix.
module.exports = [
  ...['8.2','8.3','8.4','8.5'].map(php => ({php,xdebug:'3.5.3'})),
  {php:'8.2',xdebug:'3.3.2',historical:true},
  {php:'8.3',xdebug:'3.4.7',historical:true},
];
