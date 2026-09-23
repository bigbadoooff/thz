#!/usr/bin/perl
# Reference harness: runs FHEM's own THZ_Set from docs/legacy/00_THZ.pm
# against a simulated heat pump and prints the SET telegrams it sends, plus
# FHEM's THZ_Parse1 decoding of the initial blocks.
#
# Only FHEM's runtime (logging, readings, serial I/O) is stubbed; the
# telegram encoding, parsing tables and read-modify-write logic are the
# unmodified module code. Delays (select(undef, undef, undef, x)) are
# removed so the run is fast.
#
# Input (JSON on stdin):
#   {"module": path, "firmware": "2.06",
#    "blocks": {"17": "<hex data after the address byte>", ...},
#    "cases": [["p01RoomTempDay", "21"], ...]}
# Output (JSON on stdout):
#   {"sets": {"<param> <value>": {"telegrams": [hex, ...]} | {"error": msg}},
#    "parsed": {"<block>": "<THZ_Parse1 output for the initial block>"}}
use strict;
use warnings;
use JSON::PP;

BEGIN {
    # FHEM helper modules the THZ module "use"s; not needed for THZ_Set.
    $INC{"$_.pm"} = 1 for qw(SetExtensions Blocking DevIo);
}

package main;

# FHEM globals the module refers to (normally provided by fhem.pl).
our (%defs, %attr, %data, %selectlist, %intAt, $init_done, $reread_active,
     $readingFnAttributes);
$init_done = 0;

sub Log3 { }
sub readingsSingleUpdate { }
sub AttrVal { my ($name, $attr_name, $default) = @_;
    return defined $attr{$name}{$attr_name} ? $attr{$name}{$attr_name} : $default; }
sub ReadingsVal { return $_[2]; }

my $input = decode_json(do { local $/; <STDIN> });

my $src = do {
    open my $fh, "<", $input->{module} or die "cannot read module: $!";
    local $/; <$fh>;
};
$src =~ s/select\(undef,\s*undef,\s*undef,\s*[^)]*\)/1/g;
{
    local $SIG{__WARN__} = sub { };
    eval $src;
    die "loading THZ module failed: $@" if $@;
}

my %blocks = map { uc($_) => uc($input->{blocks}{$_}) } keys %{ $input->{blocks} };
my @sent;

sub unescape_hex {
    my ($hex) = @_;
    $hex = THZ_replacebytes($hex, "1010", "10");
    return THZ_replacebytes($hex, "2B18", "2B");
}

{
    no warnings qw(redefine once);
    *main::THZ_AvoidCollisions = sub ($) { };
    *main::THZ_Get = sub ($@) { return ""; };
    *main::THZ_Get_Comunication = sub ($$) {
        my ($hash, $telegram) = @_;
        my $body = unescape_hex(substr($telegram, 4, length($telegram) - 8));
        my $payload = substr($body, 2);    # drop checksum
        if (substr($telegram, 0, 4) eq "0180") {
            push @sent, $telegram;
            return (undef, "");
        }
        my $addr = substr($payload, 0, 2);
        die "unknown block $addr" unless defined $blocks{$addr};
        my $data = $addr . $blocks{$addr};
        my $crc = THZ_checksum("0100XX" . $data . "1003");
        return (undef, $crc . $data);
    };
}

my $name = "thz";
my $hash = { NAME => $name, STATE => "opened", DeviceName => "none" };
$defs{$name} = $hash;
$attr{$name}{firmware} = $input->{firmware};
THZ_Attr("set", $name, "firmware", $input->{firmware});

my %result;
for my $case (@{ $input->{cases} }) {
    my ($param, $value) = @$case;
    @sent = ();
    my $ret = eval { THZ_Set($hash, $name, $param, $value) };
    my $key = "$param $value";
    if ($@) {
        $result{$key} = { error => "$@" };
    } elsif (!@sent) {
        $result{$key} = { error => "no SET sent: " . ($ret // "") };
    } else {
        $result{$key} = { telegrams => [@sent] };
    }
}
my %parsed;
for my $addr (keys %blocks) {
    my $data = $addr . $blocks{$addr};
    my $crc = THZ_checksum("0100XX" . $data . "1003");
    $parsed{$addr} = THZ_Parse1($hash, $crc . $data);
}
print encode_json({ sets => \%result, parsed => \%parsed });
