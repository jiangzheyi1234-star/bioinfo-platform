#! usr/bin/perl -w
use strict;

open FA, "<$ARGV[0]";
open OU, ">$ARGV[1]";
$/=">";<FA>;
while (<FA>){
chomp;
my @line = split /\s+/,$_;
my $id = $line[0];
my $seq = $line[1];
print OU "SEQUENCE_ID=$line[0]\nSEQUENCE_TEMPLATE=$line[1]\n=\n";
}
close FA;
close OU;
